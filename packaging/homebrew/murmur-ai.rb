# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.16"
  sha256 "4C8306C8260CA72F188E57F42B67B592243AE4A710870C8ED12FE49088A56E71"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.16/Murmur.AI_1.2.16_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
