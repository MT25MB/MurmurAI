# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.80"
  sha256 "6F676AFFE134C9F40228FF721C894E8CECC39C1F7E5826234BAFEB45403BD3C1"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.80/Murmur.AI_1.2.80_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
