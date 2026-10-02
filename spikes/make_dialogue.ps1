Add-Type -AssemblyName System.Speech
$lines = Get-Content -Encoding UTF8 "spikes/test_audio/dialogue.txt"
$i = 0
foreach ($l in $lines) {
  $voice, $text = $l -split '\|', 2
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $s.SelectVoice("Microsoft $voice Desktop")
  $fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
  $s.SetOutputToWaveFile(("spikes/test_audio/parts/{0:D2}_{1}.wav" -f $i, $voice), $fmt)
  $s.Speak($text); $s.Dispose(); $i++
}
