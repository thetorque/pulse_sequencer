//------------------------------------------------------------------------
// Counters.v
//
// HDL for the counters sample.  This HDL describes two counters operating
// on different board clocks and with slightly different functionality.
// The counter controls and counter values are connected to endpoints so
// that FrontPanel may control and observe them.
//
// Copyright (c) 2005-2011
// Opal Kelly Incorporated
//------------------------------------------------------------------------

`default_nettype none

module Counters(
	input  wire [4:0]   okUH,
	output wire [3:0]   okHU,
	inout  wire [31:0]  okUHU,
	input  wire [3:0]   okRSVD,
	inout  wire         okAA,

	input  wire         sys_clkp,
	input  wire         sys_clkn,
	
	output wire [3:0]   led
	);

// Clock
wire sys_clk;
IBUFGDS osc_clk(.O(sys_clk), .I(sys_clkp), .IB(sys_clkn));

// Target interface bus:
wire         okClk;
wire [112:0] okHE;
wire [64:0]  okEH;

// Endpoint connections:
wire [31:0]  ep00wire;
wire [31:0]  ep20wire, ep21wire, ep22wire;
wire [31:0]  ep40wire;
wire [31:0]  ep60trig, ep61trig;

// Counter 1:
reg  [23:0] div1;
reg         clk1div;
reg  [7:0]  count1;
reg         count1eq00;
reg         count1eq80;
wire        reset1;
wire        disable1;

// Counter 2:
reg  [23:0] div2;
reg         clk2div;
reg  [7:0]  count2;
reg         count2eqFF;
wire        reset2;
wire        up2;
wire        down2;
wire        autocount2;

// Counter 1:
assign reset1     = ep00wire[0];
assign disable1   = ep00wire[1];
assign autocount2 = ep00wire[2];
assign ep20wire   = {24'd0, count1};
assign ep21wire   = {24'd0, count2};
assign ep22wire   = {32'h0000};

// Counter 2:
assign reset2     = ep40wire[0];
assign up2        = ep40wire[1];
assign down2      = ep40wire[2];
assign ep60trig   = {30'b000000, count1eq80, count1eq00};
assign ep61trig   = {31'b0000000, count2eqFF};

function [3:0] xem7305_led;
input [3:0] a;
integer i;
begin
	for(i=0; i<4; i=i+1) begin: u
		xem7305_led[i] = (a[i]==1'b1) ? (1'b0) : (1'bz);
	end
end
endfunction

assign led = xem7305_led(count1);

// Counter #1
// + Counting using a divided sysclk.
// + Reset sets the counter to 0.
// + Disable turns off the counter.
always @(posedge sys_clk) begin
	div1 <= div1 - 1;
	if (div1 == 24'h000000) begin
		div1 <= 24'h400000;
		clk1div <= 1'b1;
	end else begin
		clk1div <= 1'b0;
	end
	
	if (clk1div == 1'b1) begin
		if (reset1 == 1'b1)
			count1 <= 8'h00;
		else if (disable1 == 1'b0)
			count1 <= count1 + 1;
		end

	if (count1 == 8'h00)
		count1eq00 <= 1'b1;
	else
		count1eq00 <= 1'b0;

	if (count1 == 8'h80)
		count1eq80 <= 1'b1;
	else
		count1eq80 <= 1'b0;
end


// Counter #2
// + Reset, up, and down control counter.
// + If autocount is enabled, a divided sys_clk can also
//   upcount.
always @(posedge sys_clk) begin
	div2 <= div2 - 1;
	if (div2 == 24'h000000) begin
		div2 <= 24'h100000;
		clk2div <= 1'b1;
	end else begin
		clk2div <= 1'b0;
	end
   
	if (reset2 == 1'b1)
		count2 <= 8'h00;
	else if (up2 == 1'b1)
		count2 <= count2 + 1;
	else if (down2 == 1'b1)
		count2 <= count2 - 1;
	else if ((autocount2 == 1'b1) && (clk2div == 1'b1))
		count2 <= count2 + 1;

	if (count2 == 8'hff)
		count2eqFF <= 1'b1;
	else
		count2eqFF <= 1'b0;
end


// Instantiate the okHost and connect endpoints.
wire [65*5-1:0]  okEHx;
okHost okHI(
	.okUH(okUH),
	.okHU(okHU),
	.okUHU(okUHU),
	.okRSVD(okRSVD),
	.okAA(okAA),
	.okClk(okClk),
	.okHE(okHE), 
	.okEH(okEH)
);

okWireOR # (.N(5)) wireOR (okEH, okEHx);

okWireIn     wi00(.okHE(okHE),                             .ep_addr(8'h00), .ep_dataout(ep00wire));
okWireOut    wo20(.okHE(okHE), .okEH(okEHx[ 0*65 +: 65 ]), .ep_addr(8'h20), .ep_datain(ep20wire));
okWireOut    wo21(.okHE(okHE), .okEH(okEHx[ 1*65 +: 65 ]), .ep_addr(8'h21), .ep_datain(ep21wire));
okWireOut    wo22(.okHE(okHE), .okEH(okEHx[ 2*65 +: 65 ]), .ep_addr(8'h22), .ep_datain(ep22wire));
okTriggerIn  ti40(.okHE(okHE),                             .ep_addr(8'h40), .ep_clk(sys_clk), .ep_trigger(ep40wire));
okTriggerOut to60(.okHE(okHE), .okEH(okEHx[ 3*65 +: 65 ]), .ep_addr(8'h60), .ep_clk(sys_clk), .ep_trigger(ep60trig));
okTriggerOut to61(.okHE(okHE), .okEH(okEHx[ 4*65 +: 65 ]), .ep_addr(8'h61), .ep_clk(sys_clk), .ep_trigger(ep61trig));

endmodule
`default_nettype wire
