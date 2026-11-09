`timescale 1ns/1ps
// One provisional activation vector, committed only by a valid terminal word.
// Each80-bit word holds eight activations plus outlier/sign prediction metadata.
// Registered activation/metadata read ports are inaccessible before commit.
module tri_oracle_activation_cache (
    input logic clk,rst_n,cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [9:0] cfg_strips,
    input logic in_valid,
    output logic in_ready,
    input logic in_last,in_error,
    input logic [31:0] in_tag,
    input logic [9:0] in_index,
    input logic [3:0] in_count,
    input logic [127:0] in_norm_q8,
    input logic [7:0] in_outlier_mask,
    input logic [63:0] in_activation,
    output logic done_valid,
    input logic done_ready,
    output logic done_error,
    output logic [31:0] done_tag,
    input logic release_valid,
    output logic release_ready,
    input logic meta_req_valid,
    output logic meta_req_ready,
    input logic [8:0] meta_req_index,
    output logic meta_rsp_valid,
    input logic meta_rsp_ready,
    output logic meta_rsp_error,
    output logic [8:0] meta_rsp_index,
    output logic [31:0] meta_rsp_tag,
    output logic [127:0] meta_rsp_norm,
    input logic read_req_valid,
    output logic read_req_ready,
    input logic [8:0] read_req_index,
    input logic [4:0] read_req_length,
    output logic read_rsp_valid,
    input logic read_rsp_ready,
    output logic read_rsp_last,read_rsp_error,
    output logic [63:0] read_rsp_data
);
    logic [79:0] memory [0:511];
    logic busy,writing,committed,fault;
    logic [31:0] tag;
    logic [9:0] strips,seen;
    logic [7:0] incoming_signs,expected_outliers;
    logic word_bad,expected_last,read_bad;
    logic [8:0] read_index;
    logic [4:0] read_remaining;
    function automatic logic [127:0] expand_proxy(input logic [15:0] metadata);
        begin
            for(int lane=0;lane<8;lane++) begin
                if(!metadata[lane]) expand_proxy[lane*16+:16]=16'd0;
                else if(metadata[lane+8]) expand_proxy[lane*16+:16]=-16'sd769;
                else expand_proxy[lane*16+:16]=16'd769;
            end
        end
    endfunction
    always_comb begin
        for(int lane=0;lane<8;lane++) begin
            incoming_signs[lane]=in_norm_q8[lane*16+15];
            expected_outliers[lane]=$signed(in_norm_q8[lane*16+:16])>16'sd768 ||
                $signed(in_norm_q8[lane*16+:16])< -16'sd768;
        end
        expected_last={1'b0,seen}+11'd1=={1'b0,strips};
        word_bad=in_error || in_tag!=tag || in_count!=4'd8 || in_index!=seen ||
            seen>=strips || in_last!=expected_last || in_outlier_mask!=expected_outliers;
        read_bad=read_req_length==0 || read_req_length>5'd16 ||
            11'(read_req_index)+11'(read_req_length)>11'(strips);
        cfg_ready=!busy;
        in_ready=busy && writing;
        done_tag=tag;
        release_ready=busy && !writing && !done_valid && !meta_rsp_valid && !read_rsp_valid;
        meta_req_ready=busy && committed && !done_valid && !release_valid &&
            (!meta_rsp_valid || meta_rsp_ready);
        read_req_ready=busy && committed && !done_valid && !release_valid && !read_rsp_valid;
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            busy<=0;writing<=0;committed<=0;fault<=0;tag<='0;strips<='0;seen<='0;
            done_valid<=0;done_error<=0;
            meta_rsp_valid<=0;meta_rsp_error<=0;meta_rsp_index<='0;
            meta_rsp_tag<='0;meta_rsp_norm<='0;
            read_rsp_valid<=0;read_rsp_last<=0;read_rsp_error<=0;read_rsp_data<='0;
            read_index<='0;read_remaining<='0;
        end else begin
            if(cfg_valid && cfg_ready) begin
                busy<=1;writing<=1;committed<=0;
                fault<=cfg_strips==0 || cfg_strips>10'd512;
                tag<=cfg_tag;strips<=cfg_strips;seen<='0;done_error<=0;
            end
            if(in_valid && in_ready) begin
                fault<=fault || word_bad;
                if(!fault && !word_bad)
                    memory[in_index[8:0]]<={incoming_signs,in_outlier_mask,in_activation};
                if(seen!=10'd1023) seen<=seen+10'd1;
                if(in_last) begin
                    writing<=0;done_valid<=1;done_error<=fault || word_bad;
                    committed<=!fault && !word_bad;
                end
            end
            if(done_valid && done_ready) done_valid<=0;
            if(meta_rsp_valid && meta_rsp_ready) meta_rsp_valid<=0;
            if(meta_req_valid && meta_req_ready) begin
                meta_rsp_valid<=1;meta_rsp_tag<=tag;meta_rsp_index<=meta_req_index;
                meta_rsp_error<={1'b0,meta_req_index}>=strips;
                if({1'b0,meta_req_index}>=strips) meta_rsp_norm<='0;
                else meta_rsp_norm<=expand_proxy(memory[meta_req_index][79:64]);
            end
            if(read_req_valid && read_req_ready) begin
                read_rsp_valid<=1;read_rsp_error<=read_bad;
                read_rsp_last<=read_bad || read_req_length==5'd1;
                read_index<=read_req_index;read_remaining<=read_req_length;
                if(read_bad) read_rsp_data<='0;
                else read_rsp_data<=memory[read_req_index][63:0];
            end
            if(read_rsp_valid && read_rsp_ready) begin
                if(read_rsp_last) read_rsp_valid<=0;
                else begin
                    read_index<=read_index+9'd1;
                    read_remaining<=read_remaining-5'd1;
                    read_rsp_last<=read_remaining==5'd2;
                    read_rsp_data<=memory[read_index+9'd1][63:0];
                end
            end
            if(release_valid && release_ready) begin
                busy<=0;committed<=0;
            end
        end
    end
endmodule
