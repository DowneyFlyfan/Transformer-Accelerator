"""Measure full-prefix attention error for the composed head on its held-out trace."""

import json
import math
from pathlib import Path

from prepare_tri_oracle_batch425_softmax import (
    AutoTokenizer, CLIPImageProcessorPil, GIB, Image, LlavaForConditionalGeneration,
    LlavaProcessor, ROOT, _dot, _quantize, check_memory, np, sha256, torch,
)
from run_tri_oracle_batch425_softmax import fixed_probabilities
from tri_oracle_integer_reference import _requantize


@torch.inference_mode()
def main():
    check_memory(14*GIB)
    assert torch.cuda.mem_get_info()[0]>12*GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    capture=ROOT/".cache/model_reference/batch430"
    ref_path=capture/"reference.json"
    ref=json.loads(ref_path.read_text())
    previous_path=ROOT/".cache/model_reference/batch429/reference.json"
    previous=json.loads(previous_path.read_text())
    gains_path=ROOT/"records/batch429_qkv_equalization.json"
    calibration=json.loads(gains_path.read_text())
    assert calibration["held_out_question"]==ref["question"] and ref["question"] not in calibration["calibration_questions"]
    compact_path=ROOT/"records/batch422_compact_decoder_result.json"
    compact=json.loads(compact_path.read_text())
    manifest=ROOT/".cache/model_reference/vqav2_pilot/manifest.json"
    sample=json.loads(manifest.read_text())["samples"][0]
    anchor=compact["cases"]["compact_and_streaming"][0]
    assert anchor["question_id"]==sample["question_id"]==ref["question"]
    mode=compact["native_fixture_modes"].index("compact_and_streaming")
    map_path=Path(compact["native_fixture"])/f"map_{mode}.hex"
    operand_path=capture/"expected.bin"
    hashes=ref["source_sha256"].copy()
    for path in (ref_path,previous_path,gains_path,compact_path,manifest,map_path,operand_path,Path(__file__)):
        hashes[str(path)]=sha256(path)
    assert hashes[str(operand_path)]==ref["fixture_sha256"]["expected.bin"]
    assert all(sha256(Path(path))==digest for path,digest in hashes.items())
    model_dir=ROOT/".cache/model_reference/tiny_llava_v1"
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
    ids=batch["input_ids"]
    embedded=model.model.get_input_embeddings()(ids)
    vision=torch.cat(model.model.get_image_features(batch["pixel_values"],return_dict=True).pooler_output,dim=0)
    embedded=embedded.masked_scatter(model.model.get_placeholder_mask(ids,embedded,vision),vision.to(embedded.dtype))
    language=model.model.language_model
    positions=torch.tensor(ref["original_positions"],device="cuda")
    decode=language.embed_tokens(torch.tensor([[anchor["answer_tokens"][0]]],device="cuda"))
    # Hidden rows [compact prompt plus decode,2048], with original positions for rotary encoding.
    hidden=language.layers[0].input_layernorm(torch.cat((embedded[:,positions[:-1]],decode),dim=1))[0]
    attention=language.layers[0].self_attn
    cosine,sine=language.rotary_emb(hidden[None],positions[None])
    cosine,sine=cosine[0,:,:32],sine[0,:,:32]

    def rotate(vector):
        lo,hi=vector[:,:32],vector[:,32:]
        return torch.cat((lo*cosine-hi*sine,hi*cosine+lo*sine),dim=1)

    # Floating reference for one group [compact token,64].
    qf=rotate(attention.q_proj(hidden)[:,:64])
    kf=rotate(attention.k_proj(hidden)[:,:64])
    vf=attention.v_proj(hidden)[:,:64]
    # Keep native query/key bytes and their scores fixed. Scale only the value projection.
    q,k,v=np.frombuffer(operand_path.read_bytes(),dtype=np.int8).reshape(3,len(positions),64).astype(np.int32)
    gain=torch.exp2(torch.tensor(calibration["selected_input_gain_log2"],device="cuda",dtype=torch.float32))
    act,ae=_quantize(hidden/gain,per_row=True)
    weight,we=_quantize(attention.v_proj.weight[:64]*gain)
    value_exponent=previous["output_exponents"][36]
    right=value_exponent-ae-int(we)
    assert bool((right>=0).all())
    compensated=_requantize(_dot(act,weight),right,8).cpu().numpy().astype(np.int32)
    origins=[int(word,16) for word in map_path.read_text().splitlines()[:576]]
    rank_by_position={position:rank for rank,position in enumerate(ref["original_positions"])}
    results=[]
    for row in ref["rows"]:
        rank,position=row["rank"],row["position"]
        visible=set(range(rank+1))
        if ref["head_streaming"] and len(visible)>64:
            visible=set(range(32))|set(range(rank-31,rank+1))
        selected=sorted(visible)
        counts={index:0 for index in selected}
        expanded=[]
        for original in range(position+1):
            image_index=original-ref["image_start"]
            representative=ref["image_start"]+origins[image_index] if 0<=image_index<576 else original
            compact_rank=rank_by_position[representative]
            if compact_rank in visible:
                counts[compact_rank]+=1
                expanded.append(compact_rank)
        scores=[max(-32768,min(32767,round(math.ldexp(int(q[rank]@k[index]),ref["score_shift"])))) for index in selected]
        codes=np.asarray(fixed_probabilities(scores,[counts[index] for index in selected]),dtype=np.int64)
        baseline=codes@v[selected]
        assert baseline.tolist()==row["output"]
        adjusted=codes@compensated[selected]
        target=(((qf[rank:rank+1]@kf[expanded].T)*0.125).softmax(-1)@vf[expanded])[0]
        scale=2.0**value_exponent/65535
        def relative(components):
            actual=torch.tensor(components,device="cuda")*scale
            return float(torch.linalg.vector_norm(actual-target)/torch.linalg.vector_norm(target))
        results.append(dict(original_position=position,baseline_relative_error=relative(baseline),
                            value_scaled_relative_error=relative(adjusted)))
    assert all(sha256(Path(path))==digest for path,digest in hashes.items())
    report=dict(state="trained_attention_relative_error_measured",question=ref["question"],head=0,
                fixed_native_query_key=True,value_scaling_selected_on_disjoint_prompts=True,
                scaled_value_path_native_verified=False,rows=results,inputs_sha256=hashes)
    output=ROOT/"records/batch430_attention_error.json"
    with output.open("x") as stream:
        stream.write(json.dumps(report,indent=2)+"\n")
    print("BATCH430_ERROR",results)


if __name__=="__main__":
    main()
