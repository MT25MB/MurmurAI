# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.74"
  sha256 "F97B1B7765B37CB499FF59F8E96B23BB7D4F663D0D75B282938AF3DE8442204F"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.74/Murmur.AI_1.2.74_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
