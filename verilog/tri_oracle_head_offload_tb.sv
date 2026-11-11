`timescale 1ns/1ps
module tri_oracle_head_offload_tb;
    logic clk = 0, rst_n = 0, map_ready;
    logic [31:0] known_heads = '0, streaming_heads = '0;
    logic [4:0] lookup_head = 0, cluster_owner, core_owner;
    always #5 clk = ~clk;

    tri_oracle_head_offload dut (.*);

    function automatic int initial_owner(input int head);
        return head % 20;
    endfunction

    task automatic await_map;
        #1;
        if (map_ready) $fatal(1, "HEAD_OFFLOAD_STALE_MAP_READY");
        do @(negedge clk); while (!map_ready);
    endtask

    task automatic check_map(input bit require_moves);
        int initial_slots[20] = '{default:0}, cluster_slots[20] = '{default:0}, core_slots[20] = '{default:0};
        int initial_cluster_heavy[5] = '{default:0}, initial_core_heavy[20] = '{default:0};
        int cluster_heavy[5] = '{default:0}, cluster_light[5] = '{default:0};
        int core_heavy[20] = '{default:0}, core_light[20] = '{default:0};
        int initial_cluster_cost = 0, cluster_cost = 0, initial_core_cost = 0, core_cost = 0;
        for (int head = 0; head < 32; head++) begin
            int home = initial_owner(head);
            lookup_head = 5'(head);
            #1;
            if (!map_ready || cluster_owner >= 20 || core_owner >= 20)
                $fatal(1, "HEAD_OFFLOAD_INVALID_OWNER head=%0d", head);
            if (!known_heads[head]) begin
                if (cluster_owner != 5'(home) || core_owner != 5'(home))
                    $fatal(1, "HEAD_OFFLOAD_UNKNOWN_HEAD_MOVED");
            end else begin
                initial_slots[home]++;
                cluster_slots[cluster_owner]++;
                core_slots[core_owner]++;
                if (streaming_heads[head]) begin
                    cluster_light[cluster_owner[4:2]]++;
                    core_light[core_owner]++;
                end else begin
                    initial_cluster_heavy[home/4]++;
                    initial_core_heavy[home]++;
                    cluster_heavy[cluster_owner[4:2]]++;
                    core_heavy[core_owner]++;
                end
            end
        end
        for (int source = 0; source < 20; source++) begin
            if (initial_slots[source] != cluster_slots[source] || initial_slots[source] != core_slots[source])
                $fatal(1, "HEAD_OFFLOAD_SLOT_CAPACITY");
            initial_core_cost += initial_core_heavy[source] * initial_core_heavy[source];
            core_cost += core_heavy[source] * core_heavy[source];
            for (int target = 0; target < 20; target++)
                if (core_light[target] > 0 && core_heavy[source] > core_heavy[target] + 1)
                    $fatal(1, "HEAD_OFFLOAD_CORE_STILL_IMBALANCED");
        end
        for (int source = 0; source < 5; source++) begin
            initial_cluster_cost += initial_cluster_heavy[source] * initial_cluster_heavy[source];
            cluster_cost += cluster_heavy[source] * cluster_heavy[source];
            for (int target = 0; target < 5; target++)
                if (cluster_light[target] > 0 && cluster_heavy[source] > cluster_heavy[target] + 1)
                    $fatal(1, "HEAD_OFFLOAD_CLUSTER_STILL_IMBALANCED");
        end
        if (require_moves && !(cluster_cost < initial_cluster_cost && core_cost < initial_core_cost))
            $fatal(1, "HEAD_OFFLOAD_NO_IMPROVEMENT");
        $display("HEAD_OFFLOAD_WORK cluster=%0d->%0d core=%0d->%0d", initial_cluster_cost, cluster_cost,
                 initial_core_cost, core_cost);
    endtask

    initial begin
        repeat (2) @(negedge clk);
        rst_n = 1;
        known_heads = 32'h0008_0000;
        await_map();
        check_map(0);
        @(negedge clk);
        known_heads = '1;
        streaming_heads = ~32'h00f0_000f;
        await_map();
        check_map(1);

        @(negedge clk);
        known_heads = 32'h00ff_ff00;
        streaming_heads = 32'h0f00_000f;
        #1;
        if (map_ready) $fatal(1, "HEAD_OFFLOAD_CHANGE_UNFENCED");
        repeat (10) @(negedge clk);
        known_heads = 32'hf0f0_000f;
        streaming_heads = 32'hf000_0000;
        await_map();
        check_map(1);
        $display("HEAD_OFFLOAD_PASS configurations=3");
        $finish;
    end

    initial begin
        #50000;
        $fatal(1, "HEAD_OFFLOAD_WATCHDOG");
    end
endmodule
