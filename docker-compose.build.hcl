group "default" {
  targets = ["backend", "frontend", "tools"]
}

variable "REGISTRY" {
  default = "ghcr.io"
}

variable "IMAGE_NAMESPACE" {
  default = "owner/reverse-auctions-platform"
}

variable "IMAGE_TAG" {
  default = "dev"
}

target "backend" {
  context    = "./backend"
  dockerfile = "./backend/Dockerfile"
  platforms  = ["linux/amd64"]
  tags = [
    "${REGISTRY}/${IMAGE_NAMESPACE}/backend:${IMAGE_TAG}",
    "${REGISTRY}/${IMAGE_NAMESPACE}/backend:latest"
  ]
}

target "frontend" {
  context    = "./frontend"
  dockerfile = "./frontend/Dockerfile"
  platforms  = ["linux/amd64"]
  tags = [
    "${REGISTRY}/${IMAGE_NAMESPACE}/frontend:${IMAGE_TAG}",
    "${REGISTRY}/${IMAGE_NAMESPACE}/frontend:latest"
  ]
}

target "tools" {
  context    = "."
  dockerfile = "./Dockerfile.tools"
  platforms  = ["linux/amd64"]
  tags = [
    "${REGISTRY}/${IMAGE_NAMESPACE}/tools:${IMAGE_TAG}",
    "${REGISTRY}/${IMAGE_NAMESPACE}/tools:latest"
  ]
}
