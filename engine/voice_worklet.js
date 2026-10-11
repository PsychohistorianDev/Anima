/* Batch microphone PCM without recording or sending any audio off the machine. */
class ParlorMicrophone extends AudioWorkletProcessor {
  constructor() { super(); this.blocks = []; this.length = 0; }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) {
      this.blocks.push(new Float32Array(channel));
      this.length += channel.length;
      if (this.length >= sampleRate * 0.025) {
        const pcm = new Float32Array(this.length);
        let offset = 0;
        for (const block of this.blocks) { pcm.set(block, offset); offset += block.length; }
        this.port.postMessage(pcm, [pcm.buffer]);
        this.blocks = []; this.length = 0;
      }
    }
    return true;
  }
}
registerProcessor('parlor-microphone', ParlorMicrophone);
