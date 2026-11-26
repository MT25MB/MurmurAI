# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.56"
  sha256 "5D44F5B8341EE8739FFB9F8F9E8BB6FC8723B1B1A099DBC1877732930C39708F"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.56/Murmur.AI_1.2.56_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
