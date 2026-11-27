# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.61"
  sha256 "AE3C2C55FD8D8C65F052D4D38C26DB9B048146C983224057CC2101074F141C02"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.61/Murmur.AI_1.2.61_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
