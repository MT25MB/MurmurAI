# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.62"
  sha256 "F6FBA915E91CA9B368BA034BAE72A797D00113B8274603CCF48055FDB860A0B6"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.62/Murmur.AI_1.2.62_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
