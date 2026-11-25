# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.31"
  sha256 "015C9CE2A32E5992DA59210E3F7CEBAB850FEC595C29AC2299EA5FDD9B267890"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.31/Murmur.AI_1.2.31_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
