# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.21"
  sha256 "52FF9CAFDD52E8F185AA231D0264926802A29BFD592DFBB20E8152A9CB945FD1"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.21/Murmur.AI_1.2.21_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
