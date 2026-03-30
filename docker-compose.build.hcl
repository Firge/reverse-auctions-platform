group "default" {
  targets = ["backend", "frontend", "tools", "smtp-worker", "smtp-relay"]
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
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
  tags = [
    "${REGISTRY}/${IMAGE_NAMESPACE}/backend:${IMAGE_TAG}",
    "${REGISTRY}/${IMAGE_NAMESPACE}/backend:latest"
  ]
}

target "frontend" {
  context    = "./frontend"
  dockerfile = "./Dockerfile"
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

target "smtp-worker" {
  context    = "./smtp/service"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
  tags = [
    "${REGISTRY}/${IMAGE_NAMESPACE}/smtp-worker:${IMAGE_TAG}",
    "${REGISTRY}/${IMAGE_NAMESPACE}/smtp-worker:latest"
  ]
}

target "smtp-relay" {
  context    = "./smtp/postfix"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
  tags = [
    "${REGISTRY}/${IMAGE_NAMESPACE}/smtp-relay:${IMAGE_TAG}",
    "${REGISTRY}/${IMAGE_NAMESPACE}/smtp-relay:latest"
  ]
}
