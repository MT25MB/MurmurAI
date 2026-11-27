# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.70"
  sha256 "C57BBF386E0977EAB8E62127981AB8AE799762F15DF7A1635026ACFAF5E53489"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.70/Murmur.AI_1.2.70_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
