`timescale 1ns/1ps
// Local 16-bit fixed-point implementation: gate/up/output have8 fraction bits.
// LUT samples round(256*x/(1+exp(-x))), x=-8+i/16, i=0..256.
// Linear interpolation; tails approximate SiLU by0 (negative) or x (positive).
// Gated output rounds ties away from zero and saturates to signed16 bits.
// Three elastic stages: SiLU interpolation, multiply, round/saturate.
// Precision and approximation are local choices, not disclosed paper settings.
module tri_oracle_silu_gate (
    input wire clk,rst_n,in_valid,out_ready,
    input wire signed [15:0] in_gate,in_up,
    input wire [15:0] in_tag,
    output wire in_ready,
    output reg out_valid,
    output reg signed [15:0] out_data,
    output reg [15:0] out_tag
);
    reg silu_valid,product_valid;
    reg signed [15:0] silu_data,saved_up;
    reg signed [31:0] product;
    reg [15:0] silu_tag,product_tag;
    wire output_ready=!out_valid || out_ready;
    wire product_ready=!product_valid || output_ready;
    wire silu_ready=!silu_valid || product_ready;
    assign in_ready=silu_ready;
    function automatic signed [15:0] lut(input [8:0] index);
        begin
            case(index)
                9'd0: lut=-16'sd1;
                9'd1: lut=-16'sd1;
                9'd2: lut=-16'sd1;
                9'd3: lut=-16'sd1;
                9'd4: lut=-16'sd1;
                9'd5: lut=-16'sd1;
                9'd6: lut=-16'sd1;
                9'd7: lut=-16'sd1;
                9'd8: lut=-16'sd1;
                9'd9: lut=-16'sd1;
                9'd10: lut=-16'sd1;
                9'd11: lut=-16'sd1;
                9'd12: lut=-16'sd1;
                9'd13: lut=-16'sd1;
                9'd14: lut=-16'sd1;
                9'd15: lut=-16'sd2;
                9'd16: lut=-16'sd2;
                9'd17: lut=-16'sd2;
                9'd18: lut=-16'sd2;
                9'd19: lut=-16'sd2;
                9'd20: lut=-16'sd2;
                9'd21: lut=-16'sd2;
                9'd22: lut=-16'sd2;
                9'd23: lut=-16'sd2;
                9'd24: lut=-16'sd2;
                9'd25: lut=-16'sd3;
                9'd26: lut=-16'sd3;
                9'd27: lut=-16'sd3;
                9'd28: lut=-16'sd3;
                9'd29: lut=-16'sd3;
                9'd30: lut=-16'sd3;
                9'd31: lut=-16'sd4;
                9'd32: lut=-16'sd4;
                9'd33: lut=-16'sd4;
                9'd34: lut=-16'sd4;
                9'd35: lut=-16'sd4;
                9'd36: lut=-16'sd5;
                9'd37: lut=-16'sd5;
                9'd38: lut=-16'sd5;
                9'd39: lut=-16'sd5;
                9'd40: lut=-16'sd6;
                9'd41: lut=-16'sd6;
                9'd42: lut=-16'sd6;
                9'd43: lut=-16'sd7;
                9'd44: lut=-16'sd7;
                9'd45: lut=-16'sd7;
                9'd46: lut=-16'sd8;
                9'd47: lut=-16'sd8;
                9'd48: lut=-16'sd9;
                9'd49: lut=-16'sd9;
                9'd50: lut=-16'sd9;
                9'd51: lut=-16'sd10;
                9'd52: lut=-16'sd10;
                9'd53: lut=-16'sd11;
                9'd54: lut=-16'sd11;
                9'd55: lut=-16'sd12;
                9'd56: lut=-16'sd13;
                9'd57: lut=-16'sd13;
                9'd58: lut=-16'sd14;
                9'd59: lut=-16'sd15;
                9'd60: lut=-16'sd15;
                9'd61: lut=-16'sd16;
                9'd62: lut=-16'sd17;
                9'd63: lut=-16'sd18;
                9'd64: lut=-16'sd18;
                9'd65: lut=-16'sd19;
                9'd66: lut=-16'sd20;
                9'd67: lut=-16'sd21;
                9'd68: lut=-16'sd22;
                9'd69: lut=-16'sd23;
                9'd70: lut=-16'sd24;
                9'd71: lut=-16'sd25;
                9'd72: lut=-16'sd26;
                9'd73: lut=-16'sd27;
                9'd74: lut=-16'sd29;
                9'd75: lut=-16'sd30;
                9'd76: lut=-16'sd31;
                9'd77: lut=-16'sd32;
                9'd78: lut=-16'sd34;
                9'd79: lut=-16'sd35;
                9'd80: lut=-16'sd36;
                9'd81: lut=-16'sd38;
                9'd82: lut=-16'sd39;
                9'd83: lut=-16'sd41;
                9'd84: lut=-16'sd42;
                9'd85: lut=-16'sd44;
                9'd86: lut=-16'sd45;
                9'd87: lut=-16'sd47;
                9'd88: lut=-16'sd49;
                9'd89: lut=-16'sd50;
                9'd90: lut=-16'sd52;
                9'd91: lut=-16'sd53;
                9'd92: lut=-16'sd55;
                9'd93: lut=-16'sd56;
                9'd94: lut=-16'sd58;
                9'd95: lut=-16'sd60;
                9'd96: lut=-16'sd61;
                9'd97: lut=-16'sd62;
                9'd98: lut=-16'sd64;
                9'd99: lut=-16'sd65;
                9'd100: lut=-16'sd66;
                9'd101: lut=-16'sd67;
                9'd102: lut=-16'sd68;
                9'd103: lut=-16'sd69;
                9'd104: lut=-16'sd70;
                9'd105: lut=-16'sd71;
                9'd106: lut=-16'sd71;
                9'd107: lut=-16'sd71;
                9'd108: lut=-16'sd71;
                9'd109: lut=-16'sd71;
                9'd110: lut=-16'sd71;
                9'd111: lut=-16'sd70;
                9'd112: lut=-16'sd69;
                9'd113: lut=-16'sd68;
                9'd114: lut=-16'sd66;
                9'd115: lut=-16'sd64;
                9'd116: lut=-16'sd62;
                9'd117: lut=-16'sd59;
                9'd118: lut=-16'sd56;
                9'd119: lut=-16'sd52;
                9'd120: lut=-16'sd48;
                9'd121: lut=-16'sd44;
                9'd122: lut=-16'sd39;
                9'd123: lut=-16'sd34;
                9'd124: lut=-16'sd28;
                9'd125: lut=-16'sd22;
                9'd126: lut=-16'sd15;
                9'd127: lut=-16'sd8;
                9'd128: lut=16'sd0;
                9'd129: lut=16'sd8;
                9'd130: lut=16'sd17;
                9'd131: lut=16'sd26;
                9'd132: lut=16'sd36;
                9'd133: lut=16'sd46;
                9'd134: lut=16'sd57;
                9'd135: lut=16'sd68;
                9'd136: lut=16'sd80;
                9'd137: lut=16'sd92;
                9'd138: lut=16'sd104;
                9'd139: lut=16'sd117;
                9'd140: lut=16'sd130;
                9'd141: lut=16'sd144;
                9'd142: lut=16'sd158;
                9'd143: lut=16'sd172;
                9'd144: lut=16'sd187;
                9'd145: lut=16'sd202;
                9'd146: lut=16'sd217;
                9'd147: lut=16'sd233;
                9'd148: lut=16'sd249;
                9'd149: lut=16'sd265;
                9'd150: lut=16'sd281;
                9'd151: lut=16'sd297;
                9'd152: lut=16'sd314;
                9'd153: lut=16'sd331;
                9'd154: lut=16'sd348;
                9'd155: lut=16'sd365;
                9'd156: lut=16'sd382;
                9'd157: lut=16'sd399;
                9'd158: lut=16'sd416;
                9'd159: lut=16'sd434;
                9'd160: lut=16'sd451;
                9'd161: lut=16'sd468;
                9'd162: lut=16'sd486;
                9'd163: lut=16'sd504;
                9'd164: lut=16'sd521;
                9'd165: lut=16'sd539;
                9'd166: lut=16'sd556;
                9'd167: lut=16'sd574;
                9'd168: lut=16'sd591;
                9'd169: lut=16'sd609;
                9'd170: lut=16'sd627;
                9'd171: lut=16'sd644;
                9'd172: lut=16'sd662;
                9'd173: lut=16'sd679;
                9'd174: lut=16'sd697;
                9'd175: lut=16'sd714;
                9'd176: lut=16'sd732;
                9'd177: lut=16'sd749;
                9'd178: lut=16'sd766;
                9'd179: lut=16'sd784;
                9'd180: lut=16'sd801;
                9'd181: lut=16'sd818;
                9'd182: lut=16'sd835;
                9'd183: lut=16'sd853;
                9'd184: lut=16'sd870;
                9'd185: lut=16'sd887;
                9'd186: lut=16'sd904;
                9'd187: lut=16'sd921;
                9'd188: lut=16'sd938;
                9'd189: lut=16'sd955;
                9'd190: lut=16'sd972;
                9'd191: lut=16'sd989;
                9'd192: lut=16'sd1006;
                9'd193: lut=16'sd1022;
                9'd194: lut=16'sd1039;
                9'd195: lut=16'sd1056;
                9'd196: lut=16'sd1073;
                9'd197: lut=16'sd1089;
                9'd198: lut=16'sd1106;
                9'd199: lut=16'sd1123;
                9'd200: lut=16'sd1139;
                9'd201: lut=16'sd1156;
                9'd202: lut=16'sd1173;
                9'd203: lut=16'sd1189;
                9'd204: lut=16'sd1206;
                9'd205: lut=16'sd1222;
                9'd206: lut=16'sd1239;
                9'd207: lut=16'sd1255;
                9'd208: lut=16'sd1271;
                9'd209: lut=16'sd1288;
                9'd210: lut=16'sd1304;
                9'd211: lut=16'sd1321;
                9'd212: lut=16'sd1337;
                9'd213: lut=16'sd1353;
                9'd214: lut=16'sd1370;
                9'd215: lut=16'sd1386;
                9'd216: lut=16'sd1402;
                9'd217: lut=16'sd1419;
                9'd218: lut=16'sd1435;
                9'd219: lut=16'sd1451;
                9'd220: lut=16'sd1467;
                9'd221: lut=16'sd1484;
                9'd222: lut=16'sd1500;
                9'd223: lut=16'sd1516;
                9'd224: lut=16'sd1532;
                9'd225: lut=16'sd1548;
                9'd226: lut=16'sd1565;
                9'd227: lut=16'sd1581;
                9'd228: lut=16'sd1597;
                9'd229: lut=16'sd1613;
                9'd230: lut=16'sd1629;
                9'd231: lut=16'sd1645;
                9'd232: lut=16'sd1662;
                9'd233: lut=16'sd1678;
                9'd234: lut=16'sd1694;
                9'd235: lut=16'sd1710;
                9'd236: lut=16'sd1726;
                9'd237: lut=16'sd1742;
                9'd238: lut=16'sd1758;
                9'd239: lut=16'sd1774;
                9'd240: lut=16'sd1790;
                9'd241: lut=16'sd1806;
                9'd242: lut=16'sd1823;
                9'd243: lut=16'sd1839;
                9'd244: lut=16'sd1855;
                9'd245: lut=16'sd1871;
                9'd246: lut=16'sd1887;
                9'd247: lut=16'sd1903;
                9'd248: lut=16'sd1919;
                9'd249: lut=16'sd1935;
                9'd250: lut=16'sd1951;
                9'd251: lut=16'sd1967;
                9'd252: lut=16'sd1983;
                9'd253: lut=16'sd1999;
                9'd254: lut=16'sd2015;
                9'd255: lut=16'sd2031;
                9'd256: lut=16'sd2047;
                default: lut=0;
            endcase
        end
    endfunction
    function automatic signed [15:0] silu(input signed [15:0] value);
        reg [11:0] offset;
        reg signed [15:0] lower,upper;
        reg signed [31:0] blend;
        begin
            if(value<=-16'sd2048) silu=0;
            else if(value>=16'sd2048) silu=value;
            else begin
                offset=12'(17'($signed(value))+17'sd2048);
                lower=lut({1'b0,offset[11:4]});
                upper=lut({1'b0,offset[11:4]}+9'd1);
                blend=32'($signed(lower))*(32'sd16-32'({1'b0,offset[3:0]})) +
                    32'($signed(upper))*32'({1'b0,offset[3:0]});
                if(blend<0) silu=-16'((-blend+32'sd8)>>>4);
                else silu=16'((blend+32'sd8)>>>4);
            end
        end
    endfunction
    function automatic signed [15:0] round_product(input signed [31:0] value);
        reg signed [32:0] extended,rounded;
        begin
            extended={value[31],value};
            if(extended<0) rounded=-((-extended+33'sd128)>>>8);
            else rounded=(extended+33'sd128)>>>8;
            if(rounded>33'sd32767) round_product=16'sh7fff;
            else if(rounded < -33'sd32768) round_product=16'sh8000;
            else round_product=rounded[15:0];
        end
    endfunction
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            silu_valid<=0;product_valid<=0;out_valid<=0;silu_data<=0;saved_up<=0;
            product<=0;silu_tag<=0;product_tag<=0;out_data<=0;out_tag<=0;
        end else begin
            if(output_ready) begin
                out_valid<=product_valid;
                if(product_valid) begin out_data<=round_product(product);out_tag<=product_tag;end
            end
            if(product_ready) begin
                product_valid<=silu_valid;
                if(silu_valid) begin product<=silu_data*saved_up;product_tag<=silu_tag;end
            end
            if(silu_ready) begin
                silu_valid<=in_valid;
                if(in_valid) begin silu_data<=silu(in_gate);saved_up<=in_up;silu_tag<=in_tag;end
            end
        end
    end
endmodule
