# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.18"
  sha256 "E65929222E66D1C62F11394D39E3D9C1F3EF802EA8CABFF69E7C94888D810B97"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.18/Murmur.AI_1.2.18_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
