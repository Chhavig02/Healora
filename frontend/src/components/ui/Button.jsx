const VARIANT_CLASS = {
  primary: 'btn-pill',
  outline: 'btn-outline',
  white: 'btn-pill btn-white',
  ghost: 'btn-ghost',
  danger: 'btn-ghost btn-ghost-danger',
};

export default function Button({
  as: As = 'button',
  variant = 'primary',
  size,
  className = '',
  children,
  ...props
}) {
  const sizeClass = size === 'lg' ? 'btn-lg' : size === 'sm' ? 'btn-sm' : '';
  const classes = [VARIANT_CLASS[variant] || VARIANT_CLASS.primary, sizeClass, className]
    .filter(Boolean)
    .join(' ');
  return (
    <As className={classes} {...props}>
      {children}
    </As>
  );
}
