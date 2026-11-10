"""Calibrate power-of-two input-channel scaling on distinct prompts and test one held-out trace."""

import json
from pathlib import Path

from prepare_tri_oracle_batch429_qkv import round_codes
from prepare_tri_oracle_batch425_softmax import (
    AutoTokenizer, CLIPImageProcessorPil, GIB, IMAGE_TOKENS, Image,
    LlavaForConditionalGeneration, LlavaProcessor, ROOT, _dot, _quantize, check_memory, sha256, torch,
)
from tri_oracle_integer_reference import _requantize


def relative(actual, expected):
    return float(torch.linalg.vector_norm(actual-expected)/torch.linalg.vector_norm(expected))


def grouped(actual, expected):
    return {kind:relative(actual[:,low:high],expected[:,low:high])
            for kind,low,high in (("query",0,32),("key",32,36),("value",36,40))}


def dot_codes(hidden, weights, gain):
    """Return dots [token, head, feature] with separate token and head exponents."""
    activation,ae=_quantize(hidden/gain,per_row=True)
    encoded,we=_quantize((weights*gain).flatten(1),per_row=True)
    dots=_dot(activation,encoded.reshape(2560,2048)).reshape(-1,40,64)
    return dots,ae[:,0],we[:,0]


@torch.inference_mode()
def main():
    check_memory(14*GIB)
    assert torch.cuda.mem_get_info()[0]>12*GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    cache=ROOT/".cache/model_reference"
    capture=cache/"batch429"
    fixture_path=capture/"reference.json"
    fixture=json.loads(fixture_path.read_text())
    compact_path=ROOT/"records/batch422_compact_decoder_result.json"
    compact=json.loads(compact_path.read_text())
    manifest=cache/"vqav2_pilot/manifest.json"
    samples=json.loads(manifest.read_text())["samples"]
    calibration=samples[1:5]
    assert len(calibration)==4 and samples[0]["question_id"]==fixture["question"]
    hashes=fixture["source_sha256"].copy()
    for path in (fixture_path,capture/"expected.bin",manifest,compact_path,Path(__file__),
                 *(ROOT/sample["image"] for sample in calibration)):
        hashes[str(path)]=sha256(path)
    assert all(sha256(Path(path))==digest for path,digest in hashes.items())
    model_dir=cache/"tiny_llava_v1"
    tokenizer=AutoTokenizer.from_pretrained(model_dir,local_files_only=True)
    processor=LlavaProcessor(image_processor=CLIPImageProcessorPil.from_pretrained(model_dir,local_files_only=True),
                             tokenizer=tokenizer,patch_size=14,vision_feature_select_strategy="default",
                             num_additional_image_tokens=1)
    model=LlavaForConditionalGeneration.from_pretrained(model_dir,local_files_only=True,dtype=torch.float32,
                        attn_implementation="sdpa",use_kernels=False).to("cuda").eval()
    language=model.model.language_model
    layer=language.layers[0]
    attention=layer.self_attn
    weights=torch.cat([attention.q_proj.weight,attention.k_proj.weight,attention.v_proj.weight]).reshape(40,64,2048)

    def embeddings(sample):
        """Return model embeddings [1, original prompt token, 2048]."""
        with Image.open(ROOT/sample["image"]) as opened:
            image=opened.convert("RGB")
        prompt="USER: <image>\n"+sample["question"]+"\nAnswer the question using a single word or phrase.\nASSISTANT:"
        batch=processor(images=image,text=prompt,return_tensors="pt").to("cuda")
        ids=batch["input_ids"]
        assert int((ids==model.config.image_token_id).sum())==IMAGE_TOKENS
        hidden=model.model.get_input_embeddings()(ids)
        vision=torch.cat(model.model.get_image_features(batch["pixel_values"],return_dict=True).pooler_output,dim=0)
        return hidden.masked_scatter(model.model.get_placeholder_mask(ids,hidden,vision),vision.to(hidden.dtype))

    # Feature range [2048] and sparse calibration rows [64,2048] use four distinct prompts.
    act_range=torch.zeros(2048,device="cuda")
    rows=[]
    for sample in calibration:
        hidden=layer.input_layernorm(embeddings(sample))[0]
        act_range=torch.maximum(act_range,hidden.abs().amax(dim=0))
        rows.append(hidden[torch.linspace(0,hidden.shape[0]-1,16,device="cuda").long()])
    calibration_rows=torch.cat(rows,dim=0)
    ideal=(calibration_rows@weights.flatten(0,1).T).reshape(-1,40,64)
    act_log=act_range.clamp_min(2.0**-20).log2()
    weight_log=weights.abs().amax(dim=(0,1)).clamp_min(2.0**-20).log2()
    gain_logs={"baseline":torch.zeros_like(act_log)}
    for alpha in (0.25,0.5,0.75,1.0):
        raw=alpha*act_log-(1-alpha)*weight_log
        gain_logs[str(alpha)]=(raw-raw.median()).round().clamp(-8,8)
    calibration_errors={}
    for name,log_gain in gain_logs.items():
        dots,ae,we=dot_codes(calibration_rows,weights,log_gain.exp2())
        predicted=torch.ldexp(dots.float(),ae[:,None,None]+we[None,:,None])
        calibration_errors[name]=grouped(predicted,ideal)
    selected=min(calibration_errors,key=lambda name:sum(calibration_errors[name].values()))

    # The held-out row features [4,2048] use original positions, including the first decode token.
    positions=torch.tensor(fixture["positions"],device="cuda")
    prompt_hidden=embeddings(samples[0])
    decode_token=compact["cases"]["compact_and_streaming"][0]["answer_tokens"][0]
    decode_hidden=language.embed_tokens(torch.tensor([[decode_token]],device="cuda"))
    hidden=layer.input_layernorm(torch.cat((prompt_hidden[:,positions[:3]],decode_hidden),dim=1))[0]
    cos,sin=language.rotary_emb(hidden[None],positions[None])
    cos,sin=cos[0,:,:32],sin[0,:,:32]
    cq,sq=round_codes(cos,16384).to(torch.int64),round_codes(sin,16384).to(torch.int64)
    out_e=torch.tensor(fixture["output_exponents"],device="cuda",dtype=torch.int32)

    def rotate(vectors, cosine, sine):
        # Rotate query/key feature pairs [token,36 heads,32], leave the four value heads unrotated.
        qk=vectors[:,:36]
        lo,hi=qk[...,:32],qk[...,32:]
        return torch.cat((torch.cat((lo*cosine[:,None]-hi*sine[:,None],
                                     hi*cosine[:,None]+lo*sine[:,None]),dim=-1),vectors[:,36:]),dim=1)

    ideal=rotate((hidden@weights.flatten(0,1).T).reshape(4,40,64),cos,sin)
    held_out={}
    for name in dict.fromkeys(("baseline",selected)):
        dots,ae,we=dot_codes(hidden,weights,gain_logs[name].exp2())
        fractions=torch.tensor([14]*36+[0]*4,device="cuda")
        shifts=out_e[None,:]-ae[:,None]-we[None,:]+fractions[None,:]
        assert bool((shifts>=0).all())
        codes=_requantize(rotate(dots.to(torch.int64),cq,sq),shifts[...,None],8).to(torch.int8)
        if name=="baseline":
            assert codes.transpose(0,1).contiguous().cpu().numpy().tobytes()==(capture/"expected.bin").read_bytes()
        actual=torch.ldexp(codes.float(),out_e[None,:,None])
        held_out[name]=grouped(actual,ideal)|{"worst_head":max(relative(actual[:,head],ideal[:,head]) for head in range(40))}
    assert all(sha256(Path(path))==digest for path,digest in hashes.items())
    result=dict(state="held_out_qkv_equalization_measured",selected_by_calibration=selected,
                calibration_questions=[item["question_id"] for item in calibration],held_out_question=fixture["question"],
                calibration_relative_errors=calibration_errors,held_out_relative_errors=held_out,
                selected_input_gain_log2=gain_logs[selected].to(torch.int32).tolist(),
                rtl_equalized_fixture_verified=False,inputs_sha256=hashes)
    output=ROOT/"records/batch429_qkv_equalization.json"
    with output.open("x") as stream:
        stream.write(json.dumps(result,separators=(",",":"))+"\n")
    print("BATCH429_EQUALIZATION",selected,held_out)


if __name__=="__main__":
    main()
