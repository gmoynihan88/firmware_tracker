# CloudFront's origin-facing addresses: the hops that sit between a viewer and this task.
#
# uvicorn's --forwarded-allow-ips needs these so that its reverse walk through
# X-Forwarded-For skips CloudFront and returns the viewer address CloudFront appended,
# rather than stopping at CloudFront itself. The command block in ecs.tf records why the
# previous "*" was unsound, and why the VPC CIDR alone would not fix it.
#
# Read rather than pinned. AWS republishes ip-ranges.json without notice, and a
# hardcoded copy would go stale in the one direction that fails silently: a range added
# after the copy was taken is an untrusted hop, so the walk stops there and every
# visitor behind it shares a throttle bucket. Nothing would surface that but a user
# reporting a 429 they did not earn.
#
# CLOUDFRONT_ORIGIN_FACING is the narrow list -- the addresses CloudFront connects to
# origins from -- not CLOUDFRONT, which is the much larger set of edge addresses viewers
# talk to. 46 IPv4 prefixes when this was written.
data "aws_ip_ranges" "cloudfront_origin_facing" {
  services = ["cloudfront_origin_facing"]
}
