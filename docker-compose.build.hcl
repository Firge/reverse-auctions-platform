group "default" {
  targets = ["backend", "frontend", "tools"]
}

target "backend" {
  context    = "./backend"
  dockerfile = "./backend/Dockerfile"
  platforms  = ["linux/amd64"]
}

target "frontend" {
  context    = "./frontend"
  dockerfile = "./frontend/Dockerfile"
  platforms  = ["linux/amd64"]
}

target "tools" {
  context    = "."
  dockerfile = "./Dockerfile.tools"
  platforms  = ["linux/amd64"]
}
