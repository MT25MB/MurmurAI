# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.30"
  sha256 "29D187546FBAA2064FF107B0C07E5B0FA3191E756FB5B0F2D259D9F38797681A"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.30/Murmur.AI_1.2.30_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
