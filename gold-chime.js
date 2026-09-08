/**
 * Web Audio API Gold Coin Acoustic Resonance Synthesizer (22k-Pro)
 * 
 * Physical Acoustics of Pure Gold Bullion (22K / 24K):
 * - High mass density (17.5-19.3 g/cm³) produces a distinct, crystalline metallic ping.
 * - Characteristic circular plate flexural modes:
 *     Fundamental mode (0,2):  ~2800 Hz
 *     Harmonic overtone mode (0,3): ~4200 Hz (1.5x harmonic ratio)
 * - Exponential decay envelope: 0.35s natural acoustic ringdown.
 * - 5800 Hz lowpass filter tames harsh DAC step noise and shapes warm bullion luster.
 * 
 * Zero external dependencies. Self-contained vanilla JavaScript.
 */

let audioCtx = null;

/**
 * Plays the characteristic acoustic chime of a 22K/24K gold coin.
 * 
 * @param {number} [pitchModifier=1.0] - Pitch multiplier (e.g., 1.0 for 22K sovereign, 0.95 for heavy 24K bar, 1.08 for 1g coin)
 */
function playGoldCoinChime(pitchModifier = 1.0) {
  try {
    // 1. AudioContext initialization with webkit fallback & user gesture resumption
    if (!audioCtx) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) return;
      audioCtx = new AudioContextClass();
    }
    if (audioCtx.state === 'suspended') {
      audioCtx.resume().catch(() => {});
    }

    const mod = (typeof pitchModifier === 'number' && Number.isFinite(pitchModifier) && pitchModifier > 0)
      ? pitchModifier
      : 1.0;

    const now = audioCtx.currentTime;
    const decayDuration = 0.35;
    const f1 = 2800 * mod;
    const f2 = 4200 * mod;

    // 2. Dual High-Frequency Oscillators (Sine for pure metallic ring)
    const osc1 = audioCtx.createOscillator();
    const osc2 = audioCtx.createOscillator();
    osc1.type = 'sine';
    osc2.type = 'sine';
    osc1.frequency.setValueAtTime(f1, now);
    osc2.frequency.setValueAtTime(f2, now);

    // 3. Low-Pass Acoustic Filter (warms metallic ring & suppresses aliasing)
    const filter = audioCtx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(5800 * mod, now);
    filter.Q.setValueAtTime(1.5, now);

    // 4. Exponential Decay Gain Envelope (clickless 2ms attack + 0.35s natural decay)
    const gainNode = audioCtx.createGain();
    const peakGain = 0.12;
    gainNode.gain.setValueAtTime(0.0001, now);
    gainNode.gain.linearRampToValueAtTime(peakGain, now + 0.002);
    gainNode.gain.exponentialRampToValueAtTime(0.00001, now + decayDuration);

    // 5. Audio Routing: [osc1, osc2] -> gainNode -> filter -> destination
    osc1.connect(gainNode);
    osc2.connect(gainNode);
    gainNode.connect(filter);
    filter.connect(audioCtx.destination);

    // 6. Trigger playback & schedule release
    osc1.start(now);
    osc2.start(now);
    osc1.stop(now + decayDuration);
    osc2.stop(now + decayDuration);

    // 7. Automatic garbage collection on ring completion
    osc1.onended = () => {
      try {
        osc1.disconnect();
        osc2.disconnect();
        gainNode.disconnect();
        filter.disconnect();
      } catch (_) {}
    };
  } catch (_) {}
}

// Global window registration
if (typeof window !== 'undefined') {
  window.playGoldCoinChime = playGoldCoinChime;
}

// Safe proactive audio unlock on user gesture (pointerdown/keydown)
if (typeof document !== 'undefined') {
  const unlockAudio = () => {
    try {
      if (!audioCtx) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (AudioContextClass) audioCtx = new AudioContextClass();
      }
      if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume().catch(() => {});
      }
    } catch (_) {}
    document.removeEventListener('pointerdown', unlockAudio);
    document.removeEventListener('keydown', unlockAudio);
  };
  document.addEventListener('pointerdown', unlockAudio, { passive: true, once: true });
  document.addEventListener('keydown', unlockAudio, { passive: true, once: true });
}

// CommonJS export for testing
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { playGoldCoinChime };
}
