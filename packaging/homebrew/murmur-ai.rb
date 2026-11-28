# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.77"
  sha256 "9AD2B0DCC8AE08B5891E20951E139206268FDF276ACAFE9820B12D491F60D6E1"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.77/Murmur.AI_1.2.77_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
