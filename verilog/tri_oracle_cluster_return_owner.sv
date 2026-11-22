`timescale 1ns/1ps
// Attach immutable physical-core ownership to each reserved cluster output.
// The caller owns its16-entry issue queue and prevents destination reuse until
// retirement. Completions may arrive independently on four cores. A launched
// synchronous output read returns one cycle later; response metadata follows it.
module tri_oracle_cluster_return_owner (
    input logic clk,rst_n,
    input logic issue,
    input logic [3:0] issue_slot,
    input logic [2:0] issue_owner,
    input logic [15:0] reserved,
    input logic [3:0] done,
    input logic [15:0] done_slots,
    input logic [3:0] next_slot,
    output logic [3:0] read_head,
    output logic read_valid,
    output logic [3:0] read_cores,
    output logic response_pending,
    output logic [3:0] response_slot,
    output logic [2:0] response_owner,
    output logic [3:0] response_cores
);
    logic [2:0] slot_owner[16];
    logic [15:0] core_completed[4];
    logic [4:0] unread_count;

    always_comb begin
        read_cores=slot_owner[next_slot][2] ? 4'b1<<slot_owner[next_slot][1:0] : 4'hf;
        read_valid=rst_n && unread_count!=0 && reserved[next_slot];
        for(int core=0;core<4;core++)
            if(read_cores[core] && !core_completed[core][next_slot])read_valid=0;
        response_cores=response_owner[2] ? 4'b1<<response_owner[1:0] : 4'hf;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin
            read_head<=0;
            unread_count<=0;
            response_pending<=0;
            response_slot<=0;
            response_owner<=0;
            for(int core=0;core<4;core++)core_completed[core]<=0;
        end else begin
            case({issue,read_valid})
                2'b10:unread_count<=unread_count+1'b1;
                2'b01:unread_count<=unread_count-1'b1;
                default:;
            endcase
            // Retain pulses even when another owner finishes on a different
            // cycle. Unreserved destinations cannot create a new completion.
            for(int core=0;core<4;core++)
                if(done[core] && reserved[done_slots[core*4+:4]])
                    core_completed[core][done_slots[core*4+:4]]<=1;
            if(issue)begin
                slot_owner[issue_slot]<=issue_owner;
                for(int core=0;core<4;core++)core_completed[core][issue_slot]<=0;
            end
            response_pending<=read_valid;
            if(read_valid)begin
                response_slot<=next_slot;
                response_owner<=slot_owner[next_slot];
                read_head<=read_head+1'b1;
                for(int core=0;core<4;core++)core_completed[core][next_slot]<=0;
            end
        end
    end
endmodule
