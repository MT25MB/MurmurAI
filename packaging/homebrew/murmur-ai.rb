# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.9"
  sha256 "A88A8D838BD87B7D56C3C7BE393AD4C4AB9DDAB957B47FEEAFE50EF5D3476C47"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.9/Murmur.AI_1.2.9_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
