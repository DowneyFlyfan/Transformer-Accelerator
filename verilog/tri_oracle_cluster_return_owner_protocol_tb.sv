`timescale 1ns/1ps
// Direct tests of the production ownership controller's completion interface.
module tri_oracle_cluster_return_owner_protocol_tb(output logic finished=0);
    logic clk=0,rst_n=0,issue=0;
    logic [3:0] issue_slot=0,next_slot,read_head,read_cores,response_slot,response_cores;
    logic [2:0] issue_owner=0,response_owner;
    logic [15:0] reserved=0,done_slots=0;
    logic [3:0] core_done=0;
    logic read_valid,response_pending;
    logic [3:0] queue[16];
    int tail=0,responses=0;
    always #3 clk=~clk;
    always_comb next_slot=queue[read_head];
    tri_oracle_cluster_return_owner dut (
        .clk,.rst_n,.issue,.issue_slot,.issue_owner,.reserved,.done(core_done),.done_slots,.next_slot,
        .read_head,.read_valid,.read_cores,.response_pending,.response_slot,.response_owner,.response_cores
    );
    function automatic int expected_slot(input int index);
        case(index)0:return 3;1:return 7;2:return 9;3:return 12;4:return 4;5:return 10;default:return -1;endcase
    endfunction
    function automatic int expected_owner(input int index);
        case(index)0:return 4;1:return 5;2:return 0;3:return 6;4:return 7;5:return 5;default:return -1;endcase
    endfunction
    always @(negedge clk)if(rst_n && response_pending)begin
        int owner;
        owner=expected_owner(responses);
        if(response_slot!==4'(expected_slot(responses)) || response_owner!==3'(owner) ||
            response_cores!==(owner>=4 ? (4'b1<<(owner-4)) : 4'hf))
            $fatal(1,"CORE_RETURN_PROTOCOL_RESPONSE index=%0d",responses);
        responses++;
    end
    task automatic accept(input int slot,owner);
        @(negedge clk);issue=1;issue_slot=4'(slot);issue_owner=3'(owner);
        queue[tail]=4'(slot);tail++;reserved[slot]=1;
        @(posedge clk);@(negedge clk);issue=0;
    endtask
    task automatic complete(input logic [3:0] mask,input logic [15:0] slots);
        @(negedge clk);core_done=mask;done_slots=slots;
        @(posedge clk);@(negedge clk);core_done=0;
    endtask
    task automatic await_responses(input int count);
        int waits=0;
        while(responses<count)begin @(negedge clk);waits++;if(waits>30)$fatal(1,"CORE_RETURN_PROTOCOL_TIMEOUT");end
    endtask
    initial begin
        repeat(2)@(negedge clk);rst_n=1;
        accept(3,4);accept(7,5);accept(9,0);
        complete(4'b0110,16'h0970); // Core1/slot7 and core2/slot9 precede slot3.
        if(read_valid || responses!=0)$fatal(1,"CORE_RETURN_PROTOCOL_REORDER");
        complete(4'b1001,16'h9009); // Three of the four slot9 cores have finished.
        if(read_valid || responses!=0)$fatal(1,"CORE_RETURN_PROTOCOL_EARLY_ALL_CORE");
        complete(4'b0001,16'h0003);
        await_responses(2);
        if(read_valid)$fatal(1,"CORE_RETURN_PROTOCOL_MISSING_CORE_IGNORED");
        @(negedge clk);core_done=4'b0010;done_slots=16'h0090;
        @(posedge clk);@(negedge clk);core_done=0;
        if(!read_valid || read_cores!==4'hf)$fatal(1,"CORE_RETURN_PROTOCOL_ALL_CORE_MASK");
        // Read slot9 and enqueue slot12 on the same edge, with a different owner.
        issue=1;issue_slot=12;issue_owner=6;queue[tail]=12;tail++;reserved[12]=1;
        @(posedge clk);@(negedge clk);issue=0;
        complete(4'b0100,16'h0c00);
        await_responses(4);
        complete(4'b1000,16'h4000); // Unreserved completion must not satisfy a later issue.
        accept(4,7);
        repeat(2)@(negedge clk);
        if(read_valid || responses!=4)$fatal(1,"CORE_RETURN_PROTOCOL_STALE_UNRESERVED");
        complete(4'b1000,16'h4000);await_responses(5);
        accept(10,4);
        @(negedge clk);rst_n=0;reserved=0;tail=0;issue=0;core_done=0;
        repeat(2)@(negedge clk);
        if(response_pending || read_head!=0)$fatal(1,"CORE_RETURN_PROTOCOL_RESET");
        rst_n=1;accept(10,5);
        complete(4'b0001,16'h000a);
        if(read_valid || responses!=5)$fatal(1,"CORE_RETURN_PROTOCOL_OLD_OWNER_AFTER_RESET");
        complete(4'b0010,16'h00a0);await_responses(6);
        $display("CORE_RETURN_PROTOCOL_PASS cases=6 responses=6");
        finished=1;
    end
endmodule
