# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.32"
  sha256 "18B867C4FF33816C0D2D6DC86C488724284AFDADBC31A8E4B744AE79FA22C34A"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.32/Murmur.AI_1.2.32_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
