"""Connect frozen integer attention to the real compact decoder/cache interface.

B=1,N new queries,T cached tokens<=1024,H=2048 features,Q=32 query heads,
G=4 key/value heads,D=64features. Input normalization and residual/feed-forward
operations remain outside this adapter; no complete-integer/model/accuracy claim.
"""
import torch
from tri_oracle_integer_attention import encode_head_weights,project_qkv,classify_heads,attend,project_output

class IntegerAttentionAdapter:
    def __init__(self,module,decoder,index,projection_exponents,output_exponents):
        """module is a frozen real LlamaAttention; decoder supplies current frame,
        positions and cache owner. index is scalar language-layer ID. Exponents
        [40]/[32] are fixed disjoint inputs, never selected from output targets.
        Encoded matrices[40,64,H]/[32,64,H] derive from trained module weights.
        Original forward and scalar enabled/closed flags preserve disabled use.
        """
        if module.layer_idx!=index or module.head_dim!=64 or module.scaling!=.125 or module.config.hidden_size!=2048 or module.config.num_attention_heads!=32 or module.config.num_key_value_heads!=4:
            raise ValueError('Unsupported attention geometry')
        if any(getattr(module,name).bias is not None for name in ['q_proj','k_proj','v_proj','o_proj']):raise ValueError('Biased projections are not supported by this physical path')
        self.module,self.decoder,self.index=module,decoder,index
        self.enabled=self.closed=False;self.original=module.forward
        device=module.q_proj.weight.device
        self.projection_exponents=torch.as_tensor(projection_exponents,device=device,dtype=torch.int64).clone()
        self.output_exponents=torch.as_tensor(output_exponents,device=device,dtype=torch.int64).clone()
        if self.projection_exponents.shape!=(40,) or self.output_exponents.shape!=(32,):raise ValueError('Invalid fixed attention units')
        weights=torch.cat([getattr(module,name).weight for name in ['q_proj','k_proj','v_proj']]).reshape(40,64,2048)
        self.weights,self.weight_exponents=encode_head_weights(weights)
        self.output_weights,self.output_weight_exponents=encode_head_weights(module.o_proj.weight.reshape(32,64,2048))
        self.vectors=self.positions=self.state=self.cache_owner=None
        self.records=[];self.last_error=None
        self.installed=self.forward;module.forward=self.installed

    def forward(self,*arguments,**keywords):
        """Original args/kwargs pass through untouched when disabled. Integer
        hidden[B,N,H], rotary cos/sin[B,N,D] and cache come from the real caller.
        Return is the same model interface (output[B,N,H],weights=None).
        """
        if not self.enabled:return self.original(*arguments,**keywords)
        if self.closed:raise ValueError('Attention adapter is closed')
        hidden=keywords.get('hidden_states',arguments[0] if arguments else None)
        position_embeddings=keywords.get('position_embeddings',arguments[1] if len(arguments)>1 else None)
        attention_mask=keywords.get('attention_mask',arguments[2] if len(arguments)>2 else None)
        cache=keywords.get('past_key_values',arguments[3] if len(arguments)>3 else None)
        with torch.inference_mode():return self.integer_forward(hidden,position_embeddings,attention_mask,cache)

    def integer_forward(self,hidden,rotary,attention_mask,cache):
        """hidden[B,N,H] is actual current normalized input; rotary[2] contains
        original cos/sin[B,N,D]. cache is the caller's actual DynamicCache.
        Locals: new/cache vectors[40,N/T,D], positions[N]/keys[T], coefficients
        [N,32], attention accumulators[Q,N,D], output codes[N,Q,D]. K/V cache
        updates use computed signed8 codes in fixed physical units, not fixtures.
        Arithmetic and frame checks precede cache/state commit.
        """
        decoder=self.decoder;prefill=bool(decoder.prefill_active)
        if hidden is None or hidden.ndim!=3 or hidden.shape[0]!=1 or hidden.shape[2]!=2048 or self.module.training:raise ValueError('Expected one evaluation-only normalized token batch')
        if attention_mask is not None or rotary is None or cache is not decoder.cache or decoder.current_attention is not self.module or decoder.layer_index!=self.index:raise ValueError('Unexpected model attention/cache ownership')
        count=hidden.shape[1];device=hidden.device
        positions=torch.as_tensor(decoder.positions,device=device,dtype=torch.int64)
        keys=torch.as_tensor(decoder.key_positions,device=device,dtype=torch.int64)
        if positions.shape!=(count,) or not torch.equal(keys[-count:],positions):raise ValueError('Query positions do not match actual cache append')
        frame=decoder.frames[self.index]
        if frame is None:raise ValueError('A cumulative-merger frame is required')
        if prefill:
            old_count=0
            if keys.numel()!=count or cache.get_seq_length(self.index)!=0:raise ValueError('Prefill needs a fresh empty layer cache')
        else:
            if self.cache_owner is not cache or self.vectors is None or self.state is None:raise ValueError('Decode cache has no matching integer prefill')
            old_count=self.vectors.shape[1]
            if keys.numel()!=old_count+count or not torch.equal(keys[:old_count],self.positions) or cache.get_seq_length(self.index)!=old_count:raise ValueError('Decode prefix differs from cached integer state')
        if keys.numel()>1024:raise ValueError('Cache exceeds physical1024slot head banks')
        cosine,sine=rotary
        if cosine.shape!=sine.shape or cosine.shape!=(1,count,64):raise ValueError('Invalid actual rotary operands')
        coefficients=[]
        for value in [cosine,sine]:
            scaled=value[0,:,:32].double()*16384
            encoded=scaled.sign()*scaled.abs().add(.5).floor()
            if not bool(((encoded>=-32768)&(encoded<=32767)).all()):raise ValueError('Rotary words exceed signed16')
            coefficients.append(encoded.to(torch.int16))
        stage='projection'
        try:
            projected=project_qkv(hidden[0],self.weights,self.weight_exponents,self.projection_exponents,*coefficients)
            vectors=projected['vectors'] if prefill else torch.cat((self.vectors,projected['vectors']),dim=1)
            stage='head_prediction'
            state=classify_heads(vectors,self.projection_exponents,count,tuple(decoder.ratio)) if prefill else self.state
            stage='attention'
            result=attend(vectors,self.projection_exponents,keys,frame.origins,decoder.image_start,list(range(old_count,old_count+count)),state)
            stage='output_projection'
            output=project_output(result['accumulators'],self.projection_exponents,self.output_weights,self.output_weight_exponents,self.output_exponents)
        except ValueError as error:
            self.last_error=dict(layer=self.index,stage=stage,prefill=prefill,new_tokens=count,cache_tokens=keys.numel(),error=str(error))
            raise ValueError(f'Integer attention layer {self.index} {stage}: {error}') from error
        # DynamicCache receives exactly the newly computed physical K/V vectors.
        key_codes=projected['vectors'][32:36];value_codes=projected['vectors'][36:40]
        key_states=torch.ldexp(key_codes.float(),self.projection_exponents[32:36,None,None]).unsqueeze(0)
        value_states=torch.ldexp(value_codes.float(),self.projection_exponents[36:40,None,None]).unsqueeze(0)
        actual_keys,actual_values=cache.update(key_states,value_states,self.index)
        expected_keys=torch.ldexp(vectors[32:36].float(),self.projection_exponents[32:36,None,None]).unsqueeze(0)
        expected_values=torch.ldexp(vectors[36:40].float(),self.projection_exponents[36:40,None,None]).unsqueeze(0)
        if not torch.equal(actual_keys,expected_keys) or not torch.equal(actual_values,expected_values) or cache.get_seq_length(self.index)!=keys.numel():raise ValueError('Model cache does not preserve computed physical data')
        self.vectors,self.positions,self.state,self.cache_owner=vectors,keys.clone(),state,cache
        if prefill:
            decoder.streaming[self.index]=state['flags'].clone()
            decoder.streaming_count+=int(state['flags'].sum());decoder.pairs+=result['value_requests']
        self.records.append(dict(layer=self.index,prefill=prefill,new_tokens=count,cache_tokens=keys.numel(),streaming_heads=int(state['flags'].sum()),value_requests=result['value_requests']))
        decoded=torch.ldexp(output['codes'].float(),self.output_exponents[None,:,None]).reshape(1,count,2048)
        return decoded.to(hidden.dtype),None

    def close(self):
        """Restore the exact original bound forward; release only owned state."""
        if not self.closed:
            if self.module.forward is not self.installed:raise ValueError('Another caller replaced the installed attention forward')
            self.module.forward=self.original;self.enabled=False;self.closed=True
            self.vectors=self.positions=self.state=self.cache_owner=None
