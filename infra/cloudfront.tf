# CloudFront terminates TLS with its own certificate, so there is nothing to buy or
# renew until a custom domain arrives. It also gives the app one stable hostname while
# the task behind it is replaced on every deploy and every Spot interruption.

# Managed policies, looked up by name rather than by the IDs everyone copies around.
data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

# Forwards everything the viewer sent -- cookies, query strings, headers -- except Host.
# API Gateway checks the Host header against its own domain, so passing the viewer's
# through would answer 403 on every request.
data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

# A public catalogue is a page strangers may all request at once, and behind it is one
# 0.5 vCPU task. Sixty seconds of caching absorbs that, and the session cookie is part of
# the cache key so a page cached for an anonymous visitor can never be handed to the
# logged-in owner -- who sees tracking markers an anonymous visitor must not.
resource "aws_cloudfront_cache_policy" "catalog" {
  name    = "${local.name}-catalog"
  comment = "Short-lived caching for the public catalogue, keyed on the session cookie"

  # Five minutes, not one. The catalogue changes at most once a day (the scheduler
  # scrapes every 24 hours), and the cost of a miss is a 1.8MB render: measured, a cold
  # edge answers in ~1.15s against ~90ms warm. A longer TTL keeps entries alive at every
  # edge that has been hit, which is the part that actually helps a first-time visitor
  # -- warming from one place would only ever warm one of CloudFront's hundreds of PoPs.
  #
  # The ceiling on staleness for the owner: after tracking a device, the catalogue's
  # tracked markers can lag by this much. That is why it is minutes rather than hours.
  min_ttl     = 0
  default_ttl = 300
  max_ttl     = 3600

  parameters_in_cache_key_and_forwarded_to_origin {
    # Gzip only, which is not the obvious choice. CloudFront compresses dynamic
    # responses on the fly at a low Brotli quality, and on this page it loses to its
    # own gzip: measured against the live distribution, the same cached catalogue is
    # 68,685 bytes as gzip and 82,436 as Brotli. Browsers send "br" ahead of "gzip",
    # so leaving Brotli on hands almost every real visitor the 20% larger payload.
    #
    # Turning it off here makes CloudFront normalise Accept-Encoding to gzip for this
    # behaviour. It covers /catalog* only: the other two behaviours use AWS managed
    # policies, which cannot be changed without replacing them with custom ones, and
    # the measurement above is for this page.
    enable_accept_encoding_brotli = false
    enable_accept_encoding_gzip   = true

    cookies_config {
      cookie_behavior = "whitelist"

      cookies {
        items = ["firmware_tracker_session"]
      }
    }

    headers_config {
      header_behavior = "none"
    }

    query_strings_config {
      query_string_behavior = "all"
    }
  }
}

resource "aws_cloudfront_distribution" "main" {
  enabled         = true
  comment         = local.name
  http_version    = "http2and3"
  is_ipv6_enabled = true

  # North America and Europe. The edges elsewhere cost more and this has one user.
  price_class = "PriceClass_100"

  origin {
    origin_id   = "api-gateway"
    domain_name = replace(aws_apigatewayv2_api.main.api_endpoint, "https://", "")

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # The application is dynamic and behind a session cookie: caching it would serve one
  # person's dashboard to the next. CachingDisabled still gets TLS termination, HTTP/3
  # and compression at the edge.
  default_cache_behavior {
    target_origin_id         = "api-gateway"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
  }

  # Static assets are safe to cache hard because src/templating.py fingerprints every
  # URL with a hash of the file: a changed asset is a changed URL.
  ordered_cache_behavior {
    path_pattern             = "/static/*"
    target_origin_id         = "api-gateway"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_optimized.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
  }

  # POST is allowed through because /catalog/scrape/<vendor> lives under this pattern
  # and is an authenticated write; only GET and HEAD are ever cached.
  ordered_cache_behavior {
    path_pattern             = "/catalog*"
    target_origin_id         = "api-gateway"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = aws_cloudfront_cache_policy.catalog.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    # *.cloudfront.net until a domain and an ACM certificate in us-east-1 arrive; the
    # provider alias for that region is already declared in providers.tf.
    cloudfront_default_certificate = true
  }
}
