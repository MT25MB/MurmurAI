# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.1"
  sha256 "88289028E4939620191F4345C86F9CF0DE5F4366D18F32AC121D8DC8F1BD3839"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.1/Murmur.AI_1.2.1_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
