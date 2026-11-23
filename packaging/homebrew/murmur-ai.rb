# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.11"
  sha256 "CB170328C826387886047A9712954FC0D8B835AB325E6558034D9D2EE7A0BC34"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.11/Murmur.AI_1.2.11_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
