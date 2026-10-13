/**
 * Attention cues for time-critical moments (a new trip offer). Synthesised with Web Audio so no
 * sound files are needed. Browsers only allow sound after the user has interacted with the page,
 * which a driver has (they tapped "Go online"); otherwise this fails silently.
 */
let audio: AudioContext | null = null;

export function chime() {
  try {
    audio ??= new AudioContext();
    void audio.resume();
    const start = audio.currentTime;
    [880, 1175, 1568].forEach((freq, i) => {
      const osc = audio!.createOscillator();
      const gain = audio!.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      const at = start + i * 0.12;
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(0.25, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.35);
      osc.connect(gain).connect(audio!.destination);
      osc.start(at);
      osc.stop(at + 0.4);
    });
  } catch {
    /* no audio available */
  }
}

export function buzz(pattern: number[] = [180, 90, 180]) {
  try {
    navigator.vibrate?.(pattern);
  } catch {
    /* not supported */
  }
}
