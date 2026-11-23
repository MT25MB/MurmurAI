# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.4"
  sha256 "1EBB0C1A2A1E8D7ADC8001EE6B5FC56694381898B6E88D29B46BBA97AEDC5012"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.4/Murmur.AI_1.2.4_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
