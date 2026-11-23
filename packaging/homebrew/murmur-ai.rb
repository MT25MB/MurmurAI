# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.5"
  sha256 "8D14692952A345170C120E56B18B0561C595CFE78BAF1137BBFA9AEDEC7913D1"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.5/Murmur.AI_1.2.5_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
