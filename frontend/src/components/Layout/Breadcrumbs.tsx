import { useLocation, Link as RouterLink } from 'react-router-dom'
import { Breadcrumbs, Link, Typography } from '@mui/material'
import NavigateNextIcon from '@mui/icons-material/NavigateNext'

const routeMap: Record<string, string> = {
  '/cases': 'Дела',
  '/settings': 'Настройки',
}

export function AppBreadcrumbs() {
  const location = useLocation()
  const pathnames = location.pathname.split('/').filter((x) => x)

  if (pathnames.length === 0) {
    return null
  }

  return (
    <Breadcrumbs
      separator={<NavigateNextIcon fontSize="small" />}
      aria-label="breadcrumb"
    >
      <Link
        component={RouterLink}
        to="/"
        underline="hover"
        color="inherit"
      >
        Главная
      </Link>
      {pathnames.map((value, index) => {
        const to = `/${pathnames.slice(0, index + 1).join('/')}`
        const isLast = index === pathnames.length - 1
        const label = routeMap[to] || value

        return isLast ? (
          <Typography key={to} color="text.primary">
            {label}
          </Typography>
        ) : (
          <Link
            key={to}
            component={RouterLink}
            to={to}
            underline="hover"
            color="inherit"
          >
            {label}
          </Link>
        )
      })}
    </Breadcrumbs>
  )
}



