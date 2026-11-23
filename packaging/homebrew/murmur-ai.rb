# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.3"
  sha256 "772358BF7F7DA0EB455659FEE7206902B299F9FB0D586E44C564F0B73AFE3E95"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.3/Murmur.AI_1.2.3_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
