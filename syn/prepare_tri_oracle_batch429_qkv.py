"""Capture trained normalized activations, projection weights and rotary angles."""

import json
from pathlib import Path

from transformers.models.llama.modeling_llama import apply_rotary_pos_emb

from prepare_tri_oracle_batch425_softmax import (
    ALL_ATTENTION_FUNCTIONS, AutoTokenizer, CLIPImageProcessorPil, CompactDecoder, GIB,
    HEADS, IMAGE_TOKENS, Image, KEY_HEADS, LlavaForConditionalGeneration, LlavaProcessor,
    ROOT, _dot, _quantize, check_memory, np, sha256, torch,
)


def round_codes(values, scale):
    return (values.sign()*torch.floor(values.abs()*scale+.5)).to(torch.int16)


@torch.inference_mode()
def main():
    check_memory(15*GIB)
    assert torch.cuda.mem_get_info()[0]>12*GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    compact_path=ROOT/"records/batch422_compact_decoder_result.json"
    compact=json.loads(compact_path.read_text())
    directory=ROOT/".cache/model_reference/batch429"
    assert not directory.exists()
    manifest=ROOT/".cache/model_reference/vqav2_pilot/manifest.json"
    sample=json.loads(manifest.read_text())["samples"][0]
    reference=compact["cases"]["compact_and_streaming"][0]
    assert sample["question_id"]==reference["question_id"]
    hashes=compact["source_sha256"].copy()
    for path in (Path(__file__),compact_path,manifest):
        hashes[str(path)]=sha256(path)
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
    # IDs [1, original token]; projected visual embeddings [image token, hidden feature].
    ids=batch["input_ids"]
    positions=(ids[0]==model.config.image_token_id).nonzero().flatten().tolist()
    assert positions==list(range(positions[0],positions[0]+IMAGE_TOKENS))
    embeddings=model.model.get_input_embeddings()(ids)
    images=torch.cat(model.model.get_image_features(batch["pixel_values"],return_dict=True).pooler_output,dim=0)
    embeddings=embeddings.masked_scatter(model.model.get_placeholder_mask(ids,embeddings,images),
                                         images.to(embeddings.device,embeddings.dtype))
    original=ALL_ATTENTION_FUNCTIONS["sdpa"]
    decoder=CompactDecoder(model,original,tuple(compact["local_ratio"]))
    attention=decoder.language.layers[0].self_attn
    captures=[]
    output_exponents=[]

    def capture(module,args,kwargs):
        if not decoder.prefill_active and decoder.decode_steps!=0:
            return
        # Hidden [1, compact token, 2048]; rotary coefficients [1, compact token, 64].
        hidden=args[0] if args else kwargs["hidden_states"]
        cos,sin=kwargs["position_embeddings"]
        q=module.q_proj(hidden).view(1,-1,HEADS,64).transpose(1,2)
        k=module.k_proj(hidden).view(1,-1,KEY_HEADS,64).transpose(1,2)
        v=module.v_proj(hidden).view(1,-1,KEY_HEADS,64).transpose(1,2)
        q,k=apply_rotary_pos_emb(q,k,cos,sin)
        # Projected operands [40 heads, compact token, 64], in Q, K, V order.
        projected=torch.cat((q[0],k[0],v[0]))
        if decoder.prefill_active:
            selected=[0,hidden.shape[1]//2,hidden.shape[1]-1]
            output_exponents.extend(int(_quantize(head)[1]) for head in projected)
        else:
            selected=[0]
        assert torch.equal(cos[...,:32],cos[...,32:]) and torch.equal(sin[...,:32],sin[...,32:])
        captures.append((decoder.positions[selected].tolist(),hidden[0,selected].clone(),
                         cos[0,selected,:32].clone(),sin[0,selected,:32].clone(),projected[:,selected].clone()))

    hook=attention.register_forward_pre_hook(capture,with_kwargs=True)
    ALL_ATTENTION_FUNCTIONS["sdpa"]=decoder.attend
    try:
        answer=decoder.generate(embeddings,positions[0],"compact_and_streaming",{2},None)
    finally:
        ALL_ATTENTION_FUNCTIONS["sdpa"]=original
        hook.remove()
    assert answer==reference["answer_tokens"] and len(captures)==2 and len(output_exponents)==40
    row_positions=[position for capture in captures for position in capture[0]]
    # Four sampled rows: three prompt positions and one decode position.
    hidden=torch.cat([capture[1] for capture in captures],dim=0)
    activation,ae=_quantize(hidden,per_row=True)
    activation_exponents=[int(exponent) for exponent in ae[:,0]]
    common_exponent=max(activation_exponents)
    shift_biases=[common_exponent-exponent for exponent in activation_exponents]
    cos=round_codes(torch.cat([capture[2] for capture in captures],dim=0),16384).cpu().numpy().astype("<i2")
    sin=round_codes(torch.cat([capture[3] for capture in captures],dim=0),16384).cpu().numpy().astype("<i2")
    floating=torch.cat([capture[4] for capture in captures],dim=1).cpu().numpy()
    projections=(attention.q_proj,attention.k_proj,attention.v_proj)
    assert all(proj.bias is None for proj in projections)
    # Matrix [40 heads, 64 output features, 2048 input features].
    weights=torch.cat([proj.weight for proj in projections]).reshape(40,64,2048)
    reference_codes=[]
    reference_dots=[]
    shifts=[]
    weight_codes=[]
    float_error={}
    value_error_sources={}
    ac=activation.cpu().numpy()
    for head,weight in enumerate(weights):
        quantized,we=_quantize(weight)
        wc=quantized.cpu().numpy()
        dots=ac.astype(np.int32)@wc.astype(np.int32).T
        np.testing.assert_array_equal(dots,_dot(activation,quantized).cpu().numpy())
        reference_dots.append(dots.astype("<i4"))
        raw=dots.astype(np.int64)
        if head<36:
            low,high=raw[:,:32],raw[:,32:]
            raw=np.concatenate((low*cos-high*sin,high*cos+low*sin),axis=1)
        shift=output_exponents[head]-common_exponent-int(we)+(14 if head<36 else 0)
        effective=np.array([shift+bias for bias in shift_biases],dtype=np.int64)[:,None]
        assert 0<shift<63 and effective.max()<63
        result=(np.sign(raw)*((np.abs(raw)+(1<<(effective-1)))>>effective)).clip(-128,127).astype(np.int8)
        exact=result.astype(np.float64)*2.0**output_exponents[head]
        float_error[str(head)]=float(np.linalg.norm(exact-floating[head])/np.linalg.norm(floating[head]))
        if head>=36:
            # Isolate activation, weight, and output quantization on [sample row, head feature].
            ideal=floating[head]
            scale=2.0**output_exponents[head]
            recovered_activation=ac.astype(np.float32)*np.exp2(np.asarray(activation_exponents))[:,None]
            recovered_weight=wc.astype(np.float32)*2.0**int(we)
            estimates={"activation_only":recovered_activation@weight.cpu().numpy().T,
                       "weight_only":hidden.cpu().numpy()@recovered_weight.T,
                       "output_only":np.clip(np.sign(ideal)*np.floor(np.abs(ideal/scale)+.5),-128,127)*scale}
            value_error_sources[str(head)]={name:float(np.linalg.norm(estimate-ideal)/np.linalg.norm(ideal))
                                            for name,estimate in estimates.items()}
        shifts.append(shift)
        weight_codes.append(wc)
        reference_codes.append(result)
    print("BATCH429_QUANTIZATION",activation_exponents,sorted(float_error.items(),key=lambda item:item[1])[-5:],flush=True)
    assert all(sha256(Path(path))==digest for path,digest in hashes.items())
    directory.mkdir()
    payload={"activation.bin":ac.tobytes(),"weights.bin":np.stack(weight_codes).tobytes(),
             "cos.bin":cos.tobytes(),"sin.bin":sin.tobytes(),"expected.bin":np.stack(reference_codes).tobytes(),
             "dots.bin":np.stack(reference_dots).tobytes()}
    for filename,content in payload.items():
        (directory/filename).write_bytes(content)
    report=dict(question=sample["question_id"],positions=row_positions,tokens=4,heads=40,shifts=shifts,
                output_exponents=output_exponents,activation_exponents=activation_exponents,
                shift_biases=shift_biases,relative_error_by_head=float_error,
                value_error_sources=value_error_sources,
                source_sha256=hashes,fixture_sha256={name:sha256(directory/name) for name in payload})
    (directory/"reference.json").write_text(json.dumps(report,indent=2)+"\n")
    print("BATCH429_CAPTURE",row_positions,"worst relative error",max(float_error.values()))


if __name__=="__main__":
    main()
