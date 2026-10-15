#!/usr/bin/env bash
# Verify that nothing in this region is still billing.
#
# Run AFTER `eksctl delete cluster`. Deleting is not the same as having deleted:
# eksctl can report success while a load balancer created by a Service, or a
# volume created by a PVC, survives - because Kubernetes made them, not eksctl,
# so they are not in any CloudFormation stack.
#
#   ./k8s/eks/teardown-check.sh
#
# Exit 0 = clean. Exit 1 = something is still there.
set -uo pipefail

REGION="${AWS_REGION:-ap-southeast-2}"
FOUND=0

check() {
  local label="$1"; shift
  local out
  out="$("$@" 2>/dev/null)"
  if [ -n "$out" ]; then
    printf '\033[31mSTILL THERE\033[0m  %s\n%s\n\n' "$label" "$out"
    FOUND=1
  else
    printf '\033[32mclean\033[0m       %s\n' "$label"
  fi
}

echo "Region: $REGION"
echo

check "EKS clusters" \
  aws eks list-clusters --region "$REGION" --query 'clusters' --output text

check "EC2 instances (any state)" \
  aws ec2 describe-instances --region "$REGION" \
  --query 'Reservations[].Instances[?State.Name!=`terminated`].[InstanceId,InstanceType,State.Name]' --output text

check "NAT gateways" \
  aws ec2 describe-nat-gateways --region "$REGION" \
  --query 'NatGateways[?State!=`deleted`].[NatGatewayId,State]' --output text

check "Load balancers (ALB/NLB)" \
  aws elbv2 describe-load-balancers --region "$REGION" \
  --query 'LoadBalancers[].[LoadBalancerName,Type]' --output text

check "Load balancers (classic)" \
  aws elb describe-load-balancers --region "$REGION" \
  --query 'LoadBalancerDescriptions[].LoadBalancerName' --output text

check "EBS volumes (any state)" \
  aws ec2 describe-volumes --region "$REGION" \
  --query 'Volumes[].[VolumeId,Size,State]' --output text

check "Unattached Elastic IPs" \
  aws ec2 describe-addresses --region "$REGION" \
  --query 'Addresses[?AssociationId==null].[PublicIp,AllocationId]' --output text

check "EBS snapshots (owned by you)" \
  aws ec2 describe-snapshots --region "$REGION" --owner-ids self \
  --query 'Snapshots[].[SnapshotId,VolumeSize]' --output text

check "CloudFormation stacks (eksctl)" \
  aws cloudformation describe-stacks --region "$REGION" \
  --query 'Stacks[?starts_with(StackName,`eksctl`)].[StackName,StackStatus]' --output text

check "EKS CloudWatch log groups" \
  aws logs describe-log-groups --region "$REGION" \
  --query 'logGroups[?contains(logGroupName,`eks`)].[logGroupName,storedBytes]' --output text

echo
if [ "$FOUND" -eq 0 ]; then
  printf '\033[32mAll clear - nothing in %s is billing.\033[0m\n' "$REGION"
else
  printf '\033[31mSomething survived the teardown. Deal with it now, not tomorrow.\033[0m\n'
fi
echo
echo "NOTE: this checks ONE region. Resources in another region are invisible here."
echo "      Cost Explorer in the billing console is the only all-region view."
exit "$FOUND"
