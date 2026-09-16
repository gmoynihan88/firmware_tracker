# The custom domain: a certificate for the app's hostname, the records that validate it,
# and the record pointing that hostname at CloudFront.
#
# All of it is conditional on var.app_hostname. Left empty -- the default, and what a
# fork of this repository gets -- none of these exist and CloudFront keeps serving its
# own *.cloudfront.net certificate. The account-specific values live in terraform.tfvars
# with the rest of them, which is what keeps this repository public.
#
# The hosted zone is looked up rather than created. Registering a domain through Route 53
# creates a public zone for it and points the domain's nameservers at that zone; a second
# zone declared here would be a zone the registrar never refers anyone to, quietly
# serving records nobody resolves.

data "aws_route53_zone" "root" {
  count = var.domain_name == "" ? 0 : 1

  name         = "${var.domain_name}."
  private_zone = false
}

# CloudFront reads its certificate from us-east-1 and nowhere else, which is why
# providers.tf has carried that alias since before there was a certificate to put in it.
resource "aws_acm_certificate" "app" {
  count    = var.app_hostname == "" ? 0 : 1
  provider = aws.us_east_1

  domain_name       = var.app_hostname
  validation_method = "DNS"

  # The distribution refers to this certificate, so a replacement has to exist before
  # the one being replaced can go.
  lifecycle {
    create_before_destroy = true
  }
}

# One record for each name ACM asks to have proved. DNS validation is the reason the
# certificate renews on its own: ACM re-checks these records and reissues without
# anyone being emailed, for as long as they remain.
resource "aws_route53_record" "certificate_validation" {
  for_each = var.app_hostname == "" ? {} : {
    for option in aws_acm_certificate.app[0].domain_validation_options :
    option.domain_name => {
      name   = option.resource_record_name
      type   = option.resource_record_type
      record = option.resource_record_value
    }
  }

  zone_id = data.aws_route53_zone.root[0].zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.record]
  ttl     = 60

  # ACM asks for the same validation name again when a certificate is replaced, so
  # without this the new record collides with the one the old certificate left behind.
  allow_overwrite = true
}

# Blocks until the certificate is actually issued. The distribution reads the ARN from
# here rather than from the certificate itself, so CloudFront is never handed one that
# ACM has not finished validating.
resource "aws_acm_certificate_validation" "app" {
  count    = var.app_hostname == "" ? 0 : 1
  provider = aws.us_east_1

  certificate_arn         = aws_acm_certificate.app[0].arn
  validation_record_fqdns = [for record in aws_route53_record.certificate_validation : record.fqdn]
}

# An alias record rather than a CNAME: Route 53 answers it for free, and unlike a CNAME
# it would still work at the zone apex if the bare domain is ever pointed here too.
# AAAA as well as A, because the distribution has is_ipv6_enabled.
resource "aws_route53_record" "app" {
  for_each = var.app_hostname == "" ? toset([]) : toset(["A", "AAAA"])

  zone_id = data.aws_route53_zone.root[0].zone_id
  name    = var.app_hostname
  type    = each.value

  alias {
    name                   = aws_cloudfront_distribution.main.domain_name
    zone_id                = aws_cloudfront_distribution.main.hosted_zone_id
    evaluate_target_health = false
  }
}
