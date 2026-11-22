`timescale 1ns/1ps
// One shared64-feature probability-times-value unit. Contexts reside in the
// existing core output slots14/15, not in per-head accumulator-register copies.
// Unsigned16 probabilities retain the65535 scale; signed8 products accumulate
// in signed32 words with the same wrap semantics as attention_row426.
// Operation0 updates,1 reads a completed context,2 releases a context.
// The caller grants the existing fabric ports exclusively. A write first owns
// one idle acquisition cycle, flushing the previous client's registered error.
// fabric_lock then retains that exclusive write/error grant through both final
// CheckWrite edges; withdrawing it fails the operation. For reads, hold grant
// until acceptance, except that cancellation may withdraw an unaccepted read.
// Accepted reads always drain, including after cancellation or grant changes.
// Cancellation before a response poisons partial state and requires release;
// a response that is already valid remains stable through acknowledgement.
// Reset the unit and reserved core controllers together; use cancellation and
// release for context-local recovery without resetting peers.
module tri_oracle_attention_value_accumulator (
    input logic clk,rst_n,
    input logic req_valid,
    output logic req_ready,
    input logic [1:0] req_operation,
    input logic [4:0] req_owner,req_head,
    input logic [15:0] req_query,req_epoch,
    input logic [31:0] req_tag,
    input logic [9:0] req_key,
    input logic req_first,req_last,
    input logic [15:0] req_probability,
    input logic [511:0] req_value,
    input logic cancel,
    output logic rsp_valid,
    input logic rsp_ready,
    output logic rsp_error,
    output logic [1:0] rsp_operation,
    output logic [4:0] rsp_owner,rsp_head,
    output logic [15:0] rsp_query,rsp_epoch,
    output logic [31:0] rsp_tag,
    output logic [9:0] rsp_key,
    output logic rsp_last,
    output logic [2047:0] rsp_values,
    output logic [19:0] resident,completed,poisoned,
    output logic [4:0] busy_clusters,
    input logic fabric_grant,
    output logic fabric_lock,
    output logic memory_load_valid,
    output logic [4:0] memory_core,
    output logic [9:0] memory_address,
    output logic [1023:0] memory_write_data,
    input logic memory_load_error,
    output logic memory_read_valid,
    input logic memory_read_ready,
    output logic [4:0] memory_clusters,
    output logic [3:0] memory_slot,
    output logic [2:0] memory_core_select,
    input logic [4:0] memory_out_valid,
    output logic [4:0] memory_out_ready,
    input logic [19:0] memory_out_slot,
    input logic [5119:0] memory_out_data
);
    typedef enum logic[2:0] {Idle,ReadIssue,ReadWait,Apply,AcquireWrite,WriteHalf,CheckWrite,Respond} state_t;
    state_t state;
    logic [4:0] heads[20];
    logic [15:0] queries[20],epochs[20];
    logic [31:0] tags[20];
    logic [9:0] next_key[20];
    logic [15:0] probability;
    logic [511:0] value_word;
    logic [2047:0] working;
    logic half,aborted,invalid_request,descriptor_matches;

    always_comb begin
        descriptor_matches=0;
        invalid_request=1;
        if(req_owner<20)begin
            descriptor_matches=resident[req_owner] && heads[req_owner]==req_head && queries[req_owner]==req_query &&
                epochs[req_owner]==req_epoch && tags[req_owner]==req_tag;
            case(req_operation)
                0:if(req_first)invalid_request=resident[req_owner] || req_key!=0 || (!req_last && req_key==1023);
                  else invalid_request=!descriptor_matches || poisoned[req_owner] || completed[req_owner] ||
                      req_key!=next_key[req_owner] || (!req_last && req_key==1023);
                1:invalid_request=!descriptor_matches || poisoned[req_owner] || !completed[req_owner] ||
                    req_first || !req_last || req_key!=(next_key[req_owner]-10'd1);
                2:invalid_request=!descriptor_matches || req_first;
                default:invalid_request=1;
            endcase
        end
        req_ready=rst_n && state==Idle && !cancel;
        rsp_valid=state==Respond;
        rsp_values=rsp_error?2048'b0:working;
        memory_core=rsp_owner;
        memory_clusters=rsp_owner<20 ? 5'b1<<rsp_owner[4:2] : 5'b0;
        memory_core_select={1'b1,rsp_owner[1:0]};
        memory_slot=4'd14+4'(half);
        memory_address=(rsp_operation==2 ? 10'd16:10'd14)+10'(half);
        memory_write_data=rsp_operation==2 ? 1024'b0:working[int'(half)*1024+:1024];
        memory_load_valid=state==WriteHalf && fabric_grant && !cancel && !aborted;
        fabric_lock=(state==AcquireWrite && fabric_grant) || state==WriteHalf || state==CheckWrite;
        memory_read_valid=state==ReadIssue && fabric_grant && !cancel && !aborted;
        memory_out_ready=state==ReadWait?memory_clusters:5'b0;
        busy_clusters=state!=Idle?memory_clusters:5'b0;
    end
    task automatic fail_operation;
        rsp_error<=1;
        if(rsp_owner<20 && resident[rsp_owner])poisoned[rsp_owner]<=1;
        state<=Respond;
    endtask
    always_ff @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            state<=Idle;resident<=0;completed<=0;poisoned<=0;
            for(int owner=0;owner<20;owner++)begin heads[owner]<=0;queries[owner]<=0;epochs[owner]<=0;tags[owner]<=0;next_key[owner]<=0;end
            probability<=0;value_word<=0;working<=0;half<=0;aborted<=0;
            rsp_error<=0;rsp_operation<=0;rsp_owner<=0;rsp_head<=0;rsp_query<=0;rsp_epoch<=0;rsp_tag<=0;rsp_key<=0;rsp_last<=0;
        end else begin
            if(cancel && state!=Idle && state!=Respond)begin
                aborted<=1;rsp_error<=1;
                if(rsp_owner<20 && resident[rsp_owner])poisoned[rsp_owner]<=1;
            end
            case(state)
                Idle:if(req_valid && req_ready)begin
                    rsp_operation<=req_operation;rsp_owner<=req_owner;rsp_head<=req_head;rsp_query<=req_query;
                    rsp_epoch<=req_epoch;rsp_tag<=req_tag;rsp_key<=req_key;rsp_last<=req_last;
                    probability<=req_probability;value_word<=req_value;half<=0;aborted<=0;rsp_error<=invalid_request;
                    if(invalid_request)state<=Respond;
                    else if(req_operation==0 && req_first)begin
                        resident[req_owner]<=1;completed[req_owner]<=0;poisoned[req_owner]<=0;
                        heads[req_owner]<=req_head;queries[req_owner]<=req_query;epochs[req_owner]<=req_epoch;tags[req_owner]<=req_tag;
                        next_key[req_owner]<=0;working<=0;state<=Apply;
                    end else if(req_operation==2)begin working<=0;state<=AcquireWrite;end
                    else state<=ReadIssue;
                end
                ReadIssue:begin
                    if(cancel || aborted)fail_operation();
                    else if(fabric_grant && memory_read_ready)state<=ReadWait;
                end
                ReadWait:if(|(memory_out_valid & memory_clusters))begin
                    if(cancel || aborted || memory_out_slot[int'(rsp_owner[4:2])*4+:4]!=memory_slot)fail_operation();
                    else begin
                        working[int'(half)*1024+:1024]<=memory_out_data[int'(rsp_owner[4:2])*1024+:1024];
                        if(!half)begin half<=1;state<=ReadIssue;end
                        else if(rsp_operation==1)state<=Respond;
                        else state<=Apply;
                    end
                end
                Apply:begin
                    if(cancel || aborted)fail_operation();
                    else begin
                        for(int feature=0;feature<64;feature++)
                            working[feature*32+:32] <= $signed(working[feature*32+:32])+
                                $signed({1'b0,probability})*$signed(value_word[feature*8+:8]);
                        half<=0;state<=AcquireWrite;
                    end
                end
                AcquireWrite:begin
                    if(cancel || aborted)fail_operation();
                    else if(fabric_grant)state<=WriteHalf;
                end
                WriteHalf:begin
                    if(cancel || aborted)fail_operation();
                    else if(!fabric_grant)fail_operation();
                    else begin
                        if(memory_load_error)fail_operation();
                        else state<=CheckWrite;
                    end
                end
                CheckWrite:begin
                    if(cancel || aborted || !fabric_grant || memory_load_error)fail_operation();
                    else if(!half)begin half<=1;state<=WriteHalf;end
                    else begin
                        if(rsp_operation==0)begin next_key[rsp_owner]<=rsp_key+10'd1;completed[rsp_owner]<=rsp_last;end
                        else begin resident[rsp_owner]<=0;completed[rsp_owner]<=0;poisoned[rsp_owner]<=0;next_key[rsp_owner]<=0;end
                        state<=Respond;
                    end
                end
                Respond:if(rsp_ready)state<=Idle;
                default:fail_operation();
            endcase
        end
    end
endmodule
