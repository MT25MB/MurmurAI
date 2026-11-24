# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.14"
  sha256 "D3B7778377D46CF9DFD39B57D907FCCF37B90AD73176E55BDE25A535C4EFE1C0"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.14/Murmur.AI_1.2.14_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
