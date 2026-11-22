`timescale 1ns/1ps
// One query/key tile per occupied cluster, using the existing four arrays in
// each cluster. Two commands cover64 signed eight-bit features. This scheduler
// drives an exclusively reserved existing fabric; it instantiates no arrays,
// score buffers or memory macros. The64-byte operand register is shared.
// Results remain provisional until the held batch completion reports success.
// Cancellation or a detected output-tag error revokes unaccepted result_valid
// beats and drains them internally. Consumers must discard every provisional
// result of an errored batch, including beats consumed before that error.
// Without either revocation condition, held results obey ordinary ready/valid.
module tri_oracle_attention_score_batch (
    input logic clk,rst_n,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic [4:0] cfg_clusters,
    input logic [24:0] cfg_heads,
    input logic [159:0] cfg_rows,
    input logic [15:0] cfg_query,cfg_epoch,
    input logic [31:0] cfg_tag,
    input logic cancel,
    input logic tensor_valid,
    output logic tensor_ready,
    input logic [2:0] tensor_cluster,
    input logic [4:0] tensor_head,tensor_key,
    input logic tensor_query,
    input logic [15:0] tensor_query_rank,tensor_epoch,
    input logic [31:0] tensor_tag,
    input logic [511:0] tensor_data,
    output logic [4:0] result_valid,
    input logic [4:0] result_ready,
    output logic [5119:0] result_data,
    output logic [24:0] result_heads,
    output logic [159:0] result_rows,
    output logic [15:0] result_query,result_epoch,
    output logic [31:0] result_tag,
    output logic done_valid,
    input logic done_ready,
    output logic done_error,busy,
    output logic fabric_load_valid,
    output logic [4:0] fabric_load_core,
    output logic [1:0] fabric_load_kind,
    output logic [9:0] fabric_load_addr,
    output logic [2047:0] fabric_load_data,
    output logic [31:0] fabric_load_rows,
    input logic fabric_load_error,
    output logic [4:0] fabric_activation_reloaded,
    output logic fabric_cmd_valid,
    input logic fabric_cmd_ready,
    output logic [4:0] fabric_cmd_clusters,fabric_cmd_weight,fabric_cmd_mask,
    output logic [9:0] fabric_cmd_activation,
    output logic [3:0] fabric_cmd_output,
    output logic fabric_cmd_accumulate,
    input logic [4:0] fabric_out_valid,
    output logic [4:0] fabric_out_ready,
    input logic [19:0] fabric_out_output,
    input logic [5119:0] fabric_out_data
);
    typedef enum logic[3:0] {
        Idle,Receive,LoadVector,WriteMasks,Reload,
        IssueFirst,DrainFirst,IssueFinal,Results,Done
    } state_t;
    state_t state;
    logic [4:0] owners,query_loaded,pending;
    logic [24:0] heads;
    logic [159:0] rows,keys_loaded;
    logic [15:0] query_rank,epoch;
    logic [31:0] tag;
    logic [511:0] operand;
    logic [2:0] operand_cluster,word_index;
    logic [4:0] operand_key;
    logic operand_query,aborted,error;
    logic [5:0] mask_cursor;
    logic invalid_cfg,invalid_tensor,all_loaded,bad_output_tag;
    logic [4:0] remaining;
    logic [63:0] operand_word;

    always_comb begin
        invalid_cfg=cfg_clusters==0;
        all_loaded=1;
        bad_output_tag=0;
        for(int cluster=0;cluster<5;cluster++)begin
            if(cfg_clusters[cluster] && cfg_rows[cluster*32+:32]==0)invalid_cfg=1;
            for(int other=cluster+1;other<5;other++)
                if(cfg_clusters[cluster] && cfg_clusters[other] &&
                    cfg_heads[cluster*5+:5]==cfg_heads[other*5+:5])invalid_cfg=1;
            if(owners[cluster] && (!query_loaded[cluster] ||
                (keys_loaded[cluster*32+:32] & rows[cluster*32+:32])!=rows[cluster*32+:32]))all_loaded=0;
            if(pending[cluster] && fabric_out_valid[cluster] && fabric_out_output[cluster*4+:4]!=0)
                bad_output_tag=1;
        end
        invalid_tensor=1;
        if(tensor_query_rank==query_rank && tensor_epoch==epoch && tensor_tag==tag &&
            tensor_cluster<5 && owners[tensor_cluster] &&
            tensor_head==heads[int'(tensor_cluster)*5+:5])begin
            if(tensor_query)invalid_tensor=query_loaded[tensor_cluster] || tensor_key!=0;
            else invalid_tensor=!rows[int'(tensor_cluster)*32+int'(tensor_key)] ||
                keys_loaded[int'(tensor_cluster)*32+int'(tensor_key)];
        end

        cfg_ready=state==Idle;
        tensor_ready=state==Receive && !all_loaded && !cancel;
        busy=state!=Idle;
        done_valid=state==Done;
        done_error=error;
        result_heads=heads;result_rows=rows;
        result_query=query_rank;result_epoch=epoch;result_tag=tag;
        result_data=fabric_out_data;
        result_valid=0;
        fabric_out_ready=0;
        if(state==DrainFirst)fabric_out_ready=pending;
        if(state==Results)begin
            if(aborted || cancel || bad_output_tag)fabric_out_ready=pending;
            else begin
                result_valid=fabric_out_valid & pending;
                fabric_out_ready=result_ready & pending;
            end
        end
        remaining=pending & ~(fabric_out_valid & fabric_out_ready);

        operand_word=operand[int'(word_index)*64+:64];
        fabric_load_valid=0;fabric_load_core=0;fabric_load_kind=0;
        fabric_load_addr=0;fabric_load_data=0;fabric_load_rows='1;
        if(state==LoadVector)begin
            fabric_load_valid=1;
            fabric_load_core={operand_cluster,word_index[2:1]};
            fabric_load_addr={9'b0,word_index[0]};
            if(operand_query)begin
                fabric_load_kind=1;
                fabric_load_data[63:0]=operand_word;
            end else begin
                fabric_load_kind=0;
                fabric_load_data={32{operand_word}};
                fabric_load_rows=32'b1<<operand_key;
            end
        end
        if(state==WriteMasks)begin
            fabric_load_valid=owners[mask_cursor[5:3]];
            fabric_load_core={mask_cursor[5:3],mask_cursor[2:1]};
            fabric_load_addr={9'b0,mask_cursor[0]};fabric_load_kind=2;
            for(int row=0;row<32;row++)
                fabric_load_data[row*8+:8]=rows[int'(mask_cursor[5:3])*32+row]?8'hff:8'h00;
        end
        fabric_activation_reloaded=state==Reload?owners:5'b0;
        fabric_cmd_valid=(state==IssueFirst || state==IssueFinal) && !cancel;
        fabric_cmd_clusters=owners;
        fabric_cmd_accumulate=state==IssueFinal;
        fabric_cmd_weight=state==IssueFinal?5'd1:5'd0;
        fabric_cmd_mask=fabric_cmd_weight;
        fabric_cmd_activation=state==IssueFinal?10'd1:10'd0;
        fabric_cmd_output=0;
    end

    always_ff @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            state<=Idle;owners<=0;heads<=0;rows<=0;
            query_rank<=0;epoch<=0;tag<=0;
            query_loaded<=0;keys_loaded<=0;pending<=0;
            operand<=0;operand_cluster<=0;operand_key<=0;operand_query<=0;
            word_index<=0;mask_cursor<=0;aborted<=0;error<=0;
        end else begin
            if(cancel && state!=Idle)aborted<=1;
            case(state)
                Idle:if(cfg_valid)begin
                    owners<=cfg_clusters;heads<=cfg_heads;rows<=cfg_rows;
                    query_rank<=cfg_query;epoch<=cfg_epoch;tag<=cfg_tag;
                    query_loaded<=0;keys_loaded<=0;pending<=0;
                    aborted<=cancel;error<=invalid_cfg || cancel;
                    state<=invalid_cfg || cancel?Done:Receive;
                end
                Receive:begin
                    if(cancel)begin error<=1;state<=Done;end
                    else if(all_loaded)begin mask_cursor<=0;state<=WriteMasks;end
                    else if(tensor_valid)begin
                        if(invalid_tensor)begin error<=1;state<=Done;end
                        else begin
                            operand<=tensor_data;operand_cluster<=tensor_cluster;
                            operand_key<=tensor_key;operand_query<=tensor_query;
                            word_index<=0;state<=LoadVector;
                        end
                    end
                end
                LoadVector:begin
                    if(fabric_load_error)begin error<=1;state<=Done;end
                    else if(word_index==7)begin
                        if(operand_query)query_loaded[operand_cluster]<=1;
                        else keys_loaded[int'(operand_cluster)*32+int'(operand_key)]<=1;
                        if(aborted || cancel)begin error<=1;state<=Done;end
                        else state<=Receive;
                    end else word_index<=word_index+1'b1;
                end
                WriteMasks:begin
                    if(cancel || (fabric_load_valid && fabric_load_error))begin error<=1;state<=Done;end
                    else if(mask_cursor==39)state<=Reload;
                    else mask_cursor<=mask_cursor+1'b1;
                end
                Reload:begin
                    if(cancel)begin error<=1;state<=Done;end
                    else state<=IssueFirst;
                end
                IssueFirst,IssueFinal:begin
                    if(cancel)begin error<=1;state<=Done;end
                    else if(fabric_cmd_ready)begin
                        pending<=owners;
                        state<=state==IssueFirst?DrainFirst:Results;
                    end
                end
                DrainFirst:begin
                    pending<=remaining;
                    if(bad_output_tag)begin error<=1;aborted<=1;end
                    if(remaining==0)begin
                        if(aborted || cancel || bad_output_tag)begin error<=1;state<=Done;end
                        else state<=IssueFinal;
                    end
                end
                Results:begin
                    pending<=remaining;
                    if(bad_output_tag)begin error<=1;aborted<=1;end
                    if(remaining==0)begin
                        if(aborted || cancel || bad_output_tag)error<=1;
                        state<=Done;
                    end
                end
                Done:if(done_ready)begin state<=Idle;owners<=0;pending<=0;end
                default:begin state<=Done;error<=1;end
            endcase
        end
    end
endmodule
