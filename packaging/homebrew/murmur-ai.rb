# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.22"
  sha256 "2AAEEBA256F52AFC010CEAB28864E074CF0CD91B40E07B678BA23421B14E029F"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.22/Murmur.AI_1.2.22_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
