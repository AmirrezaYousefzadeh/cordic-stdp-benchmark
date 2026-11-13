`timescale 1ns/1ps
// tb_iter.v: testbench of the iterative units (cordic_iter, bitprod_iter).
//
// Compile with -DDUT=<module> -DNB=<input bits> -DFO=<Fo> -DLAT=<latency in cycles> -DNV=<number of vectors>
// -DVEC=\"<vector file>\". Vector file: one hex word per line, {n[NB-1:0], y[FO:0]} (golden model).
//
// Protocol checked for every operation (start given in cycle 0, when busy = 0):
//   - cycles 1 .. LAT-1: busy = 1, done = 0;
//   - cycle LAT: done = 1, busy = 0 and y equals the vector (bit-exact, 4-state compare);
//   - afterwards, until the next start: done = 0, busy = 0 and y unchanged;
//   - done is never 1 in any other cycle.
// Phase A: all vectors in order, back to back (the next start is given in the done cycle). Phase B: all vectors
// in a pseudo-random order, with 0 to 3 idle cycles between operations and random start pulses and random n while
// busy, which the unit must ignore. During reset start = 1 with random n: busy and done must stay 0.
// Ends with "PASS ..." or "FAIL ..." and returns exit status 0 or 1 from vvp.
module tb_iter;
  localparam integer NB  = `NB;
  localparam integer FO  = `FO;
  localparam integer LAT = `LAT;
  localparam integer NV  = `NV;

  reg           clk   = 1'b0;
  reg           rst_n = 1'b0;
  reg           start = 1'b0;
  reg  [NB-1:0] n     = {NB{1'b0}};
  wire          busy;
  wire          done;
  wire [FO:0]   y;

  `DUT dut (.clk(clk), .rst_n(rst_n), .start(start), .n(n), .busy(busy), .done(done), .y(y));

  always #5 clk = ~clk;

  reg  [NB+FO:0] vec [0:NV-1];
  integer errors, checked, cycles, i, k, seed, idx, gap, junk;

  task report_error(input [255:0] what, input [NB-1:0] nn, input [FO:0] ye);
    begin
      errors = errors + 1;
      if (errors <= 10)
        $display("ERROR cycle %0d: %0s: n=%0d expected y=%0d, got busy=%b done=%b y=%0d",
                 cycles, what, nn, ye, busy, done, y);
    end
  endtask

  // one operation; called at a negedge where busy = 0 (idle or done cycle); returns at the negedge of the done cycle
  task op(input [NB-1:0] nn, input [FO:0] ye, input integer junk_starts);
    integer t;
    begin
      if (busy !== 1'b0) report_error("busy = 1 when start is given", nn, ye);
      start = 1'b1;
      n = nn;
      for (t = 1; t < LAT; t = t + 1) begin
        @(negedge clk);
        cycles = cycles + 1;
        if (busy !== 1'b1 || done !== 1'b0) report_error("busy/done during the operation", nn, ye);
        // while busy: start pulses and new n must be ignored
        start = junk_starts ? $random(seed) : 1'b0;
        n = $random(seed);
      end
      @(negedge clk);
      cycles = cycles + 1;
      start = 1'b0;
      checked = checked + 1;
      if (done !== 1'b1 || busy !== 1'b0) report_error("done/busy at the stated latency", nn, ye);
      if (y !== ye) report_error("y", nn, ye);
    end
  endtask

  // idle cycles after an operation: y must hold, no done, not busy
  task idle(input integer cnt, input [NB-1:0] nn, input [FO:0] ye);
    integer t;
    begin
      for (t = 0; t < cnt; t = t + 1) begin
        start = 1'b0;
        n = $random(seed);
        @(negedge clk);
        cycles = cycles + 1;
        if (busy !== 1'b0 || done !== 1'b0) report_error("busy/done while idle", nn, ye);
        if (y !== ye) report_error("y not held until the next start", nn, ye);
      end
    end
  endtask

  initial begin
    errors = 0;
    checked = 0;
    cycles = 0;
    seed = 20261113;
    $readmemh(`VEC, vec);
    // reset with start = 1: the unit must stay idle
    rst_n = 1'b0;
    start = 1'b1;
    n = $random(seed);
    for (k = 0; k < 4; k = k + 1) begin
      @(negedge clk);
      if (busy !== 1'b0 || done !== 1'b0) begin
        errors = errors + 1;
        $display("ERROR: busy = %b, done = %b during reset", busy, done);
      end
      n = $random(seed);
    end
    rst_n = 1'b1;
    start = 1'b0;
    @(negedge clk);
    if (busy !== 1'b0 || done !== 1'b0) begin
      errors = errors + 1;
      $display("ERROR: busy = %b, done = %b after reset", busy, done);
    end
    // phase A: back to back, in order
    for (i = 0; i < NV; i = i + 1)
      op(vec[i][NB+FO:FO+1], vec[i][FO:0], 0);
    idle(2, vec[NV-1][NB+FO:FO+1], vec[NV-1][FO:0]);
    // phase B: pseudo-random order (a permutation for NV = 2^NB), random gaps, junk starts while busy
    for (i = 0; i < NV; i = i + 1) begin
      idx = (i * 37 + 11) % NV;
      junk = {$random(seed)} % 2;
      op(vec[idx][NB+FO:FO+1], vec[idx][FO:0], junk);
      gap = {$random(seed)} % 4;
      idle(gap, vec[idx][NB+FO:FO+1], vec[idx][FO:0]);
    end
    idle(2, vec[idx][NB+FO:FO+1], vec[idx][FO:0]);
    if (errors == 0 && checked == 2 * NV)
      $display("PASS vectors=%0d results_checked=%0d latency=%0d cycles=%0d", NV, checked, LAT, cycles);
    else
      $display("FAIL errors=%0d results_checked=%0d (expected %0d)", errors, checked, 2 * NV);
    $finish_and_return((errors == 0 && checked == 2 * NV) ? 0 : 1);
  end
endmodule
