"""Build a full compact prompt and decode reference using the hardware projection format."""

import json
import math
from pathlib import Path

from prepare_tri_oracle_batch429_qkv import round_codes
from prepare_tri_oracle_batch425_softmax import (
    AutoTokenizer, CLIPImageProcessorPil, GIB, IMAGE_TOKENS, Image,
    LlavaForConditionalGeneration, LlavaProcessor, ROOT, _dot, _quantize, check_memory, np, sha256, torch,
)
from run_tri_oracle_batch425_softmax import fixed_probabilities


HEADS=(0,32,36)
WIDTH=64
FEATURES=2048


@torch.inference_mode()
def main():
    check_memory(15*GIB)
    assert torch.cuda.mem_get_info()[0]>12*GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    cache=ROOT/".cache/model_reference"
    prior_dir=cache/"batch429"
    prior_path=prior_dir/"reference.json"
    prior=json.loads(prior_path.read_text())
    compact_path=ROOT/"records/batch422_compact_decoder_result.json"
    compact=json.loads(compact_path.read_text())
    manifest=cache/"vqav2_pilot/manifest.json"
    sample=json.loads(manifest.read_text())["samples"][0]
    anchor=compact["cases"]["compact_and_streaming"][0]
    assert anchor["question_id"]==sample["question_id"]==prior["question"]
    native_dir=Path(compact["native_fixture"])
    mode=compact["native_fixture_modes"].index("compact_and_streaming")
    map_path=native_dir/f"map_{mode}.hex"
    signs_path=native_dir/f"signs_{mode}.hex"
    hashes=prior["source_sha256"].copy()
    for path in (prior_path,compact_path,manifest,map_path,signs_path,Path(__file__),
                 ROOT/"syn/run_tri_oracle_batch425_softmax.py",prior_dir/"weights.bin",prior_dir/"expected.bin"):
        hashes[str(path)]=sha256(path)
    for path in (map_path,signs_path):
        assert hashes[str(path)]==compact["native_fixture_sha256"][str(path)]
    for name in ("weights.bin","expected.bin"):
        assert hashes[str(prior_dir/name)]==prior["fixture_sha256"][name]
    assert all(sha256(Path(path))==digest for path,digest in hashes.items())
    directory=cache/"batch430"
    assert not directory.exists()
    model_dir=cache/"tiny_llava_v1"
    tokenizer=AutoTokenizer.from_pretrained(model_dir,local_files_only=True)
    processor=LlavaProcessor(image_processor=CLIPImageProcessorPil.from_pretrained(model_dir,local_files_only=True),
                             tokenizer=tokenizer,patch_size=14,vision_feature_select_strategy="default",
                             num_additional_image_tokens=1)
    model=LlavaForConditionalGeneration.from_pretrained(model_dir,local_files_only=True,dtype=torch.float32,
                       attn_implementation="sdpa",use_kernels=False).to("cuda").eval()
    with Image.open(ROOT/sample["image"]) as opened:
        image=opened.convert("RGB")
    prompt="USER: <image>\n"+sample["question"]+"\nAnswer the question using a single word or phrase.\nASSISTANT:"
    batch=processor(images=image,text=prompt,return_tensors="pt").to("cuda")
    # Token IDs [1, original prompt token] and visual embeddings [image token,2048].
    ids=batch["input_ids"]
    image_positions=(ids[0]==model.config.image_token_id).nonzero().flatten().tolist()
    image_start=image_positions[0]
    assert image_positions==list(range(image_start,image_start+IMAGE_TOKENS))
    embeddings=model.model.get_input_embeddings()(ids)
    images=torch.cat(model.model.get_image_features(batch["pixel_values"],return_dict=True).pooler_output,dim=0)
    embeddings=embeddings.masked_scatter(model.model.get_placeholder_mask(ids,embeddings,images),images.to(embeddings.dtype))
    language=model.model.language_model
    prompt_len=ids.shape[1]
    origins=[int(word,16) for word in map_path.read_text().splitlines()[:IMAGE_TOKENS]]
    roots=[index for index,origin in enumerate(origins) if index==origin]
    original_positions=[*range(image_start),*(image_start+root for root in roots),
                        *range(image_start+IMAGE_TOKENS,prompt_len+1)]
    assert len(original_positions)==anchor["layer_cache_slots"][0]+1
    ranks=[original_positions.index(position) for position in prior["positions"]]
    positions=torch.tensor(original_positions,device="cuda")
    decode=language.embed_tokens(torch.tensor([[anchor["answer_tokens"][0]]],device="cuda"))
    # Normalized features [compact prompt plus decode,2048], rotary tables [token,32 pair positions].
    hidden=language.layers[0].input_layernorm(torch.cat((embeddings[:,positions[:-1]],decode),dim=1))[0]
    cos,sin=language.rotary_emb(hidden[None],positions[None])
    cq=round_codes(cos[0,:,:32],16384).cpu().numpy().astype("<i2")
    sq=round_codes(sin[0,:,:32],16384).cpu().numpy().astype("<i2")
    activation,exponents=_quantize(hidden,per_row=True)
    activation_exponents=exponents[:,0].cpu().numpy()
    ac=activation.cpu().numpy()
    common=int(max(activation_exponents))
    baseline_common=max(prior["activation_exponents"])
    weights=np.frombuffer((prior_dir/"weights.bin").read_bytes(),dtype=np.int8).reshape(40,64,2048)
    shifts=[value+baseline_common-common for value in prior["shifts"]]
    biases=(common-activation_exponents).tolist()
    operands=[]
    baseline=np.frombuffer((prior_dir/"expected.bin").read_bytes(),dtype=np.int8).reshape(40,4,64)
    for head in HEADS:
        # Dot products [compact token,64] checked independently on host and graphics processor.
        wc=weights[head]
        dots=ac.astype(np.int32)@wc.astype(np.int32).T
        np.testing.assert_array_equal(dots,_dot(activation,torch.from_numpy(wc.copy()).to("cuda")).cpu().numpy())
        raw=dots.astype(np.int64)
        if head<36:
            lo,hi=raw[:,:32],raw[:,32:]
            raw=np.concatenate((lo*cq-hi*sq,hi*cq+lo*sq),axis=1)
        effective=(shifts[head]+np.asarray(biases))[:,None]
        assert effective.min()>=0 and effective.max()<63
        quantized=(np.sign(raw)*((np.abs(raw)+(1<<np.maximum(effective-1,0))*(effective!=0))>>effective)).clip(-128,127).astype(np.int8)
        np.testing.assert_array_equal(quantized[ranks],baseline[head])
        operands.append(quantized)

    queries,keys,values=(codes.astype(np.int32) for codes in operands)
    score_shift=prior["output_exponents"][0]+prior["output_exponents"][32]+5
    alpha=4*2**(8-score_shift)
    all_dots=queries@keys.T
    inner=recent=0
    for rank in range(96,len(original_positions)-1):
        tile=rank//32*32
        cutoff=int(max(all_dots[rank,:32]))-alpha
        inner+=int(np.count_nonzero(all_dots[rank,tile-64:tile-32]>cutoff))
        recent+=int(np.count_nonzero(all_dots[rank,tile:rank+1]>cutoff))
    streaming=recent>8*inner
    rows=[]
    for rank in ranks:
        position=original_positions[rank]
        visible=list(range(rank+1))
        if streaming and len(visible)>64:
            visible=visible[:32]+visible[-32:]
        sizes=[]
        for key_rank in visible:
            key_position=original_positions[key_rank]
            if image_start<=key_position<image_start+IMAGE_TOKENS:
                sizes.append(origins[:position-image_start+1].count(key_position-image_start))
            else:
                sizes.append(1)
        assert all(size>0 for size in sizes)
        scores=[max(-32768,min(32767,round(math.ldexp(int(all_dots[rank,key]),score_shift)))) for key in visible]
        probabilities=fixed_probabilities(scores,sizes)
        output=[sum(probability*int(values[key,lane]) for key,probability in zip(visible,probabilities,strict=True))
                for lane in range(WIDTH)]
        rows.append(dict(rank=rank,position=position,visible=len(visible),output=output))

    assert all(sha256(Path(path))==digest for path,digest in hashes.items())
    directory.mkdir()
    payload={"activation.bin":ac.tobytes(),"cos.bin":cq.tobytes(),"sin.bin":sq.tobytes(),
             "expected.bin":np.stack(operands).tobytes()}
    for filename,content in payload.items():
        (directory/filename).write_bytes(content)
    result=dict(question=sample["question_id"],head_ids=HEADS,image_start=image_start,
                prompt_slots=len(original_positions)-1,original_positions=original_positions,
                shifts=shifts,shift_biases=biases,score_shift=score_shift,alpha=alpha,
                head_inner=inner,head_recent=recent,head_streaming=streaming,rows=rows,
                source_sha256=hashes,fixture_sha256={name:sha256(directory/name) for name in payload})
    (directory/"reference.json").write_text(json.dumps(result,indent=2)+"\n")
    print("BATCH430_CAPTURE",len(original_positions),ranks,"head",inner,recent,streaming)


if __name__=="__main__":
    main()
