# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.0"
  sha256 "B003197EF1076F6651843DF82F86015064F073787AA38FD3FF7F07ABE373E079"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.0/Murmur.AI_1.2.0_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
