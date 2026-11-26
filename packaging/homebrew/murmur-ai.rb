# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.44"
  sha256 "1F1AFA1EEFA8060D9BBB74FEF4762F75D5D9A15588A3DC2292E73AF7E5632D9E"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.44/Murmur.AI_1.2.44_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
