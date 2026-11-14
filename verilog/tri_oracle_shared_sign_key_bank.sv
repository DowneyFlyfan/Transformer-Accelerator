module tri_oracle_shared_sign_key_bank (
    input  logic clk,
    input  logic key_owner,
    input  logic sign_select, sign_write,
    input  logic [4:0] sign_address,
    input  logic [511:0] sign_data,
    input  logic key_select, key_write,
    input  logic [4:0] key_address,
    input  logic [511:0] key_data,
    output logic [511:0] read_data
);
    logic selected, writing;
    logic [4:0] address;
    logic [511:0] data;

    assign selected = key_owner ? key_select : sign_select;
    assign writing = key_owner ? key_write : sign_write;
    assign address = key_owner ? key_address : sign_address;
    assign data = key_owner ? key_data : sign_data;

    for (genvar part=0; part<4; part++) begin : banks
        TS5N28HPCPSVTA32X128M2FW bank (
            .CLK(clk), .CEB(!selected), .WEB(!writing),
            .A(address), .D(data[128*part+:128]), .BWEB(128'b0),
            .Q(read_data[128*part+:128])
        );
    end
endmodule
