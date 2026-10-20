// One shared media-base graph; does not run or publish any image.
group "default" { targets = ["api", "cpu"] }
target "media-base" {
  context = "."
  dockerfile = "Dockerfile"
  target = "media-base"
  tags = ["mideagent-media-base:local"]
}
target "api" {
  context = "."
  dockerfile = "Dockerfile"
  target = "runtime"
  tags = ["mideagent-api:local"]
}
target "api-broker" {
  inherits = ["api"]
  target = "broker"
  tags = ["mideagent-api-broker:local"]
}
target "cpu" {
  context = "."
  dockerfile = "agents/cpu/Dockerfile"
  target = "runtime"
  contexts = { media_base = "target:media-base" }
  tags = ["mideagent-cpu:local"]
}
target "cpu-amqp" {
  inherits = ["cpu"]
  target = "amqp"
  tags = ["mideagent-cpu-amqp:local"]
}
target "legacy-media" {
  context = "."
  dockerfile = "agents/media/Dockerfile"
  contexts = { media_base = "target:media-base" }
  tags = ["mideagent-legacy-media:local"]
}
