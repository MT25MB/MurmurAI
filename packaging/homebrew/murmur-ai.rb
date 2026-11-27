# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.60"
  sha256 "60F49FDB220C550010BF1B89ABC018BFB09BC4C85EF8A925F50D262883744B3D"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.60/Murmur.AI_1.2.60_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
