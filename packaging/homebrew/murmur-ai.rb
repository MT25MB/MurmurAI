# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.10"
  sha256 "C45B5005450BC72A6B00BD234B0591906C6C8C5A78F9DA6922E4825BE0EDE048"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.10/Murmur.AI_1.2.10_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
