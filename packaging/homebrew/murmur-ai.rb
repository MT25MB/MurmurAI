# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.23"
  sha256 "474E127BEE76F45D4F55793FB44D9769733919D491E8A2B5615A1FC4A07870D3"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.23/Murmur.AI_1.2.23_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
