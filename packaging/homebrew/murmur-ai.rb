# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.45"
  sha256 "CA5F633BDEC960D92155E6EF4550147E20FD2D2B40E19CA94639D2244D49E369"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.45/Murmur.AI_1.2.45_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
